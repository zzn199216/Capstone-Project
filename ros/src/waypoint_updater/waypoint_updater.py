#!/usr/bin/env python
import numpy as np
import rospy
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TwistStamped
from std_msgs.msg import Int32
from styx_msgs.msg import Lane, Waypoint
from scipy.spatial import KDTree

import math

'''
This node will publish waypoints from the car's current position to some `x` distance ahead.

As mentioned in the doc, you should ideally first implement a version which does not care
about traffic lights or obstacles.

Once you have created dbw_node, you will update this node to use the status of traffic lights too.

Please note that our simulator also provides the exact location of traffic lights and their
current status in `/vehicle/traffic_lights` message. You can use this message to build this node
as well as to verify your TL classifier.

TODO (for Yousuf and Aaron): Stopline location for each traffic light.
'''

LOOKAHEAD_WPS = 100 # Number of waypoints we will publish. You can change this number
MAX_DECEL = 0.28 #max deceleration factor used to update waypoints
MIN_STOP_TIME = 3.0 #minimum brake time

class WaypointUpdater(object):
	def __init__(self):
		rospy.init_node('waypoint_updater')

		# TODO: Add other member variables you need below
		self.stopline_wp_idx = -1
		self.pose = None
		self.base_waypoints = None
		self.waypoints_2d = None
		self.waypoint_tree = None
		self.is_braking = False

		# wait for message before initializing rest of the code.
		rospy.wait_for_message('/current_pose', PoseStamped)
		rospy.wait_for_message('/base_waypoints', Lane)
		rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
		self.base_waypoints_sub = rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

		# TODO: Add a subscriber for /traffic_waypoint and /obstacle_waypoint below
		rospy.Subscriber('/traffic_waypoint', Int32, self.traffic_cb)
		rospy.Subscriber('/obstacle_waypoint', Int32, self.obstacle_cb)
		rospy.Subscriber('/current_velocity', TwistStamped, self.velocity_cb)

		self.final_waypoints_pub = rospy.Publisher('final_waypoints', Lane, queue_size=1)
		
		self.loop()
		
		rospy.spin()

	def loop(self):
		rate = rospy.Rate(15) #15Hz
		while not rospy.is_shutdown():
			if self.pose and self.base_waypoints:
				#get closest waypoint
				closest_waypoint_idx = self.get_closest_waypoint_idx()
				self.publish_waypoints(closest_waypoint_idx)
			rate.sleep()

	def get_closest_waypoint_idx(self):
		x = self.pose.pose.position.x
		y = self.pose.pose.position.y
		closest_idx = self.waypoint_tree.query([x,y],1)[1]

		#check if closest is ahead or behind vehcile
		closest_coord = self.waypoints_2d[closest_idx]
		prev_coord = self.waypoints_2d[closest_idx-1]

		#equation for hyperplane through closest_coords
		cl_vect = np.array(closest_coord)
		prev_vect = np.array(prev_coord)
		pos_vect = np.array([x,y])

		val = np.dot(cl_vect-prev_vect, pos_vect-cl_vect)

		if val > 0:
			closest_idx = (closest_idx + 1) % len(self.waypoints_2d)
		return closest_idx

	def publish_waypoints(self, closest_idx):
		final_lane = self.generate_lane()
		final_lane.header = self.base_waypoints.header
		# pick every other waypoint to reduce overhead
		#final_lane.waypoints = final_lane.waypoints[0::2]
		self.final_waypoints_pub.publish(final_lane)

	def generate_lane(self):
		lane = Lane()
		closest_idx = self.get_closest_waypoint_idx()
		farthest_idx = closest_idx + LOOKAHEAD_WPS
		# division later, make sure current_vel is not zero.
		if self.current_vel < 0.1:
			non_zero_current_vel = 0.1
		else: non_zero_current_vel = self.current_vel
		#we just need subset of the entire waypoint set.
		new_base_waypoints = self.base_waypoints.waypoints[closest_idx:farthest_idx]
		#conditions for intersections (traffic lights). If they are too far, 
		#ingore them, if they are close and they are red, update waypoints with reducing velocity
		if self.stopline_wp_idx == -1 or (self.stopline_wp_idx >= farthest_idx):
			lane.waypoints = new_base_waypoints
			self.is_braking = False
		elif self.distance(self.base_waypoints.waypoints, closest_idx, self.stopline_wp_idx)/non_zero_current_vel < MIN_STOP_TIME and self.is_braking == False:
			lane.waypoints = new_base_waypoints
		else:
			lane.waypoints = self.decelerate_waypoints(new_base_waypoints, closest_idx)
			self.is_braking = True
		#testing
		#lane.waypoints = self.decelerate_waypoints(new_base_waypoints, closest_idx)
		return lane

	def decelerate_waypoints(self, waypoints, closest_idx):
		temp = []
		for i, wp in enumerate(waypoints):
		
			p = Waypoint()
			p.pose = wp.pose
			#four waypoints back from line so front of the car stops at line
			stop_idx = max(self.stopline_wp_idx - closest_idx - 4, 0)
			dist = self.distance(waypoints, i, stop_idx)
			#vel = math.sqrt(3*dist)
			#use simple multiplication is enough.
			vel = MAX_DECEL*dist
			#if velocity is low, set to zero
			if vel < 1.0:
				vel = 0.0
			
			p.twist.twist.linear.x = min(vel, wp.twist.twist.linear.x)
			temp.append(p)
			
		return temp

	def velocity_cb(self, msg):
		self.current_vel = msg.twist.linear.x

	def pose_cb(self, msg):
		# TODO: Implement
		self.pose = msg

	def waypoints_cb(self, waypoints):
		# TODO: Implement
		
		if self.waypoints_2d == None:
			self.waypoints_2d = [[waypoint.pose.pose.position.x, waypoint.pose.pose.position.y] for waypoint in waypoints.waypoints]
			self.waypoint_tree = KDTree(self.waypoints_2d)
		if self.base_waypoints == None:
			self.base_waypoints = waypoints
		# base waypoints only needs to be called once, so we can stop subscribing from the topic once we have them
		if self.base_waypoints and self.waypoints_2d:
			self.base_waypoints_sub.unregister()

	def traffic_cb(self, msg):
		# TODO: Callback for /traffic_waypoint message. Implement
		self.stopline_wp_idx = msg.data

	def obstacle_cb(self, msg):
		# TODO: Callback for /obstacle_waypoint message. We will implement it later
		pass

	def get_waypoint_velocity(self, waypoint):
		return waypoint.twist.twist.linear.x

	def set_waypoint_velocity(self, waypoints, waypoint, velocity):
		waypoints[waypoint].twist.twist.linear.x = velocity

	def distance(self, waypoints, wp1, wp2):
		dist = 0
		dl = lambda a, b: math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2  + (a.z-b.z)**2)
		for i in range(wp1, wp2+1):
			dist += dl(waypoints[wp1].pose.pose.position, waypoints[i].pose.pose.position)
			wp1 = i
		return dist


if __name__ == '__main__':
	try:
		WaypointUpdater()
	except rospy.ROSInterruptException:
		rospy.logerr('Could not start waypoint updater node.')


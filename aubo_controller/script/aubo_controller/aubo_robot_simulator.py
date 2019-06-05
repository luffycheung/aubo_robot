#!/usr/bin/env python
#
# Software License Agreement (BSD License)
# Copyright (c) 2017-2018, Aubo Robotics
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#  * Neither the name of the Southwest Research Institute, nor the names
#    of its contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import rospy
import copy
import threading
import Queue

# Publish
from sensor_msgs.msg import JointState
from control_msgs.msg import FollowJointTrajectoryFeedback
from std_msgs.msg import Int32MultiArray
from std_msgs.msg import Float32MultiArray

# Subscribe
from trajectory_msgs.msg import JointTrajectory
from trajectory_msgs.msg import JointTrajectoryPoint

# Services
from industrial_msgs.srv import GetRobotInfo, GetRobotInfoResponse

# Reference
from industrial_msgs.msg import TriState, RobotMode, ServiceReturnCode, DeviceInfo

from trajectory_speed import scale_trajectory_speed


"""
MotionController
This class simulates the motion controller for an Aubo robot.
This class IS threadsafe
"""
class MotionControllerSimulator():
    """
    Constructor of motion controller simulator
    """
    def __init__(self, num_joints, update_rate = 200, buffer_size = 0):
        # Class lock
        self.lock = threading.Lock()

        # Motion loop update rate (higher update rates result in smoother simulated motion)
        self.update_rate = update_rate
        rospy.loginfo("Setting motion update rate (hz): %f", self.update_rate)

        # Initialize motion buffer (contains joint position lists)
        self.motion_buffer = Queue.Queue(buffer_size)
        rospy.logdebug("Setting motion buffer size: %i", buffer_size)

        def_joint_names = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"]
        self.joint_names = rospy.get_param('controller_joint_names', def_joint_names)

        initial_joint_state = rospy.get_param('initial_joint_state', [0]*num_joints)
        # same_len = len(initial_joint_state) == len(self.joint_names)
        self.joint_len = num_joints
        initial_joint_state = [0]*num_joints
        # all_num  = all(type(x) is int or type(x) is float for x in initial_joint_state)
        # if not same_len or not all_num:
        #     initial_joint_state = [0]*num_joints
        #     rospy.logwarn("Invalid initial_joint_state parameter, defaulting to all-zeros "
        #                   "(len: %s, types: %s).", same_len, all_num)
        rospy.loginfo("Using initial joint state: %s", str(initial_joint_state))

         # Initialize joint position
        self.joint_positions = initial_joint_state
        rospy.logdebug("Setting initial joint state: %s", str(initial_joint_state))
        self.joint_velocities = [0]*num_joints
        self.joint_accelerations = [0]*num_joints

        self.ribBufferSize = 0
        self.ControllerConnectedFlag = 1
        self.positionUpdatedFlag = '0'
        self.pointCount = 0
        self.pointAddFinish = 0

        rospy.logdebug("Creating joint state publisher")
        self.moveit_joint_state_pub = rospy.Publisher('moveItController_cmd', JointTrajectoryPoint, queue_size=2500)

        rospy.logdebug("Creating joint state subscriber!")
        self.update_joint_state_subs = rospy.Subscriber('/aubo_driver/real_pose', Float32MultiArray, self.update_joint_state_callback)

        self.MinimumBufferSize = 800
        # Shutdown signal
        self.sig_shutdown = False

        # Stop signal
        self.sig_stop = False

        # Motion thread
        self.motion_thread = threading.Thread(target=self._motion_worker)
        self.motion_thread.daemon = True
        self.motion_thread.start()

    """
    Update the joint position from extern controller.
    """
    def update_joint_state_callback(self, msg_in):
        if not self.is_in_motion():
            self.joint_positions = msg_in.data
            rospy.loginfo('update joints, %s' , str(self.joint_positions))

    def add_motion_waypoint(self, point):
    # When add new trajectory into the buffer, here need to handle the accelerations!!
        self.motion_buffer.put(point)

    def get_joint_positions(self):
        with self.lock:
            return self.joint_positions[:]

    """
    return the status of the controller.
    """
    def is_in_motion(self):
        return not self.motion_buffer.empty()

    def shutdown(self):
        self.sig_shutdown = True
        rospy.logdebug('Motion_Controller shutdown signaled')

    def stop(self):
        rospy.logdebug('Motion_Controller stop signaled')
        with self.lock:
            self._clear_buffer()
            self.sig_stop = True

    def interpolate(self, last_pt, current_pt, alpha):
        intermediate_pt = JointTrajectoryPoint()
        for last_joint, current_joint in zip(last_pt.positions, current_pt.positions):
            intermediate_pt.positions.append(last_joint + alpha*(current_joint-last_joint))
        intermediate_pt.time_from_start = last_pt.time_from_start + rospy.Duration(alpha*(current_pt.time_from_start.to_sec() - last_pt.time_from_start.to_sec()))
        return intermediate_pt

    def _clear_buffer(self):
        with self.motion_buffer.mutex:
            self.motion_buffer.queue.clear()

    def joint_state_publisher(self):
        try:
            joint_point_msg = JointTrajectoryPoint()
            time = rospy.Time.now()

            with self.lock:
                #Joint states
                joint_point_msg.time_from_start = time
                joint_point_msg.positions = self.joint_positions
                joint_point_msg.velocities = self.joint_velocities
                joint_point_msg.accelerations = self.joint_accelerations

                self.moveit_joint_state_pub.publish(joint_point_msg)
                # rospy.loginfo('published joints : %s', str(self.joint_positions))

        except Exception as e:
            rospy.loginfo('Unexpected exception in joint state publisher: %s', e)

    """
    update the motion controller state combining with the robot controller information
    """
    def _move_to(self, point, dur):
        while self.ribBufferSize > self.MinimumBufferSize:
            rospy.loginfo('too fast!!')
            rospy.sleep(dur)

        if self.ribBufferSize == 0 and self.ControllerConnectedFlag == 0:      # motion start or no robot connected!
            rospy.sleep(dur)

        if self.ribBufferSize == 0 and self.ControllerConnectedFlag == 1:      # motion start but with robot connected!
            pass
            # rospy.loginfo('too slow slow!!')

        with self.lock:
            if not self.sig_stop:
                self.joint_positions = point.positions
                self.joint_velocities = point.velocities
                self.joint_accelerations = point.accelerations
                # self.joint_state_publisher()                #publish the control command to the robot
                # rospy.logdebug('Moved to position: %s in %s', str(self.joint_positions), str(dur))
            else:
                rospy.loginfo('Stopping motion immediately, clearing stop signal')
                self.sig_stop = False

    def _motion_worker(self):
        # first update the robot real postion
        self.positionUpdatedFlag = rospy.get_param('/aubo_driver/robot_connected', '0')
        while self.positionUpdatedFlag == '0':
            rospy.sleep( self.update_rate/400)
            self.positionUpdatedFlag = rospy.get_param('/aubo_driver/robot_connected', '0')

        rospy.loginfo('Starting motion worker in motion controller simulator')
        move_duration = rospy.Duration()
        if self.update_rate <> 0.:
            update_duration = rospy.Duration(1./self.update_rate)
        last_goal_point = JointTrajectoryPoint()
        end_goal_point = JointTrajectoryPoint()

        with self.lock:
            last_goal_point.positions = self.joint_positions[:]

        while not self.sig_shutdown:
            try:
                current_goal_point = self.motion_buffer.get()

                # If the current time from start is less than or equal to the last, then it's a new trajectory
                if current_goal_point.time_from_start <= last_goal_point.time_from_start:
                    move_duration = current_goal_point.time_from_start.to_sec()
                    intermediate_goal_point = copy.deepcopy(current_goal_point)
                    point_count = 1
                    external_axis_count = 0
                # Else it's an existing trajectory and subtract the two
                else:
                    # If current move duration is greater than update_duration, interpolate the joint positions to form a smooth trajectory
                    # Provide an exception to this rule: if update rate is <=0, do not add interpolated points
                    T = current_goal_point.time_from_start.to_sec() - last_goal_point.time_from_start.to_sec()
                    point_count += 1
                    if self.update_rate > 0:
                        ts = last_goal_point.time_from_start.to_sec()
                        # tt = ts + residual_duration
                        tk = current_goal_point.time_from_start.to_sec()
                        while move_duration < current_goal_point.time_from_start.to_sec():
                            tk1 = tk - move_duration
                            tk2 = tk1 * tk1
                            tk3 = tk2 * tk1
                            ts1 = move_duration - ts
                            ts2 = ts1 * ts1
                            ts3 = ts2 * ts1
                            t_squa = T * T
                            if self.joint_len > 6:
                                intermediate_goal_point.accelerations[external_axis_count] = (tk3*last_goal_point.accelerations[6] \
                                    + ts3*current_goal_point.accelerations[6] + (6*current_goal_point.positions[6] - \
                                    t_squa*current_goal_point.accelerations[6])*ts1 +(6*last_goal_point.positions[6] - t_squa*last_goal_point.accelerations[6])*tk1) / (6*T)
                                intermediate_goal_point.velocities[external_axis_count] = (3*ts2*current_goal_point.accelerations[6] - 3*tk2*last_goal_point.accelerations[6] \
                                        + 6*(current_goal_point.positions[6] - last_goal_point.positions[6]) - t_squa*(current_goal_point.accelerations[6] - last_goal_point.accelerations[6])) / (6*T)

                            external_axis_count = external_axis_count + 1
                            if(external_axis_count == 5):
                                external_axis_count = 0
                                for i in range(0, 6):
                                    intermediate_goal_point.positions[i] = (tk3*last_goal_point.accelerations[i] \
                                    + ts3*current_goal_point.accelerations[i] + (6*current_goal_point.positions[i] - \
                                    t_squa*current_goal_point.accelerations[i])*ts1 +(6*last_goal_point.positions[i] - t_squa*last_goal_point.accelerations[i])*tk1) / (6*T)

                                    # intermediate_goal_point.velocities[i] = (3*ts2*current_goal_point.accelerations[i] - 3*tk2*last_goal_point.accelerations[i] \
                                    #     + 6*(current_goal_point.positions[i] - last_goal_point.positions[i]) - t_squa*(current_goal_point.accelerations[i] - last_goal_point.accelerations[i])) / (6*T)
                                    #intermediate_goal_point.accelerations[i] = 2*a2[i]+6*a3[i]*t1+12*a4[i]*t2+20*a5[i]*t3
                                self._move_to(intermediate_goal_point, update_duration.to_sec())
                                self.joint_state_publisher()
#                                rospy.loginfo('interpolation Ext: %s %s %s %s %s ', str(intermediate_goal_point.accelerations[0]),
#                                                                             str(intermediate_goal_point.accelerations[1]),
#                                                                             str(intermediate_goal_point.accelerations[2]),
#                                                                             str(intermediate_goal_point.accelerations[3]),
#                                                                             str(intermediate_goal_point.accelerations[4]))
#                                rospy.loginfo('interpolation : %s ! %s @ %s # %s $ %s * %s ', str(intermediate_goal_point.positions[0]),
#                                                                             str(intermediate_goal_point.positions[1]),
#                                                                             str(intermediate_goal_point.positions[2]),
#                                                                             str(intermediate_goal_point.positions[3]),
#                                                                             str(intermediate_goal_point.positions[4]),
#                                                                             str(intermediate_goal_point.positions[5]))
                            move_duration = move_duration + update_duration.to_sec()/5

                last_goal_point = copy.deepcopy(current_goal_point)
                if(self.pointAddFinish == 1 and point_count == self.pointCount):  # last point
                    end_goal_point = copy.deepcopy(current_goal_point)
                    if self.joint_len > 6:
                        if(external_axis_count <= 0):
                            for i in range(0, 5):
                                current_goal_point.accelerations[i] = current_goal_point.positions[6]
                        else:
                            for i in range(0, external_axis_count):
                                current_goal_point.accelerations[i] = intermediate_goal_point.accelerations[i]
                            for i in range(external_axis_count, 5):
                                current_goal_point.accelerations[i] = current_goal_point.positions[6]

                    self._move_to(current_goal_point, update_duration.to_sec())
                    self.joint_state_publisher()
#                    rospy.loginfo('interpolation Ext: %s %s %s %s %s ', str(current_goal_point.accelerations[0]),
#                                                                    str(current_goal_point.accelerations[1]),
#                                                                    str(current_goal_point.accelerations[2]),
#                                                                    str(current_goal_point.accelerations[3]),
#                                                                    str(current_goal_point.accelerations[4]))
#                    rospy.loginfo('interpolation : %s ! %s @ %s # %s $ %s  * %s ', str(current_goal_point.positions[0]),
#                                                                             str(current_goal_point.positions[1]),
#                                                                             str(current_goal_point.positions[2]),
#                                                                             str(current_goal_point.positions[3]),
#                                                                             str(current_goal_point.positions[4]),
#                                                                             str(current_goal_point.positions[5]))

                    for j in range(0, 3):
                         if self.joint_len > 6:
                            for i in range(0, 5):
                                end_goal_point.accelerations[i] = end_goal_point.positions[6]
                         self._move_to(end_goal_point, update_duration.to_sec())
                         self.joint_state_publisher()
#                         rospy.loginfo('interpolation Ext: %s %s %s %s %s ', str(end_goal_point.accelerations[0]),
#                                                                         str(end_goal_point.accelerations[1]),
#                                                                         str(end_goal_point.accelerations[2]),
#                                                                         str(end_goal_point.accelerations[3]),
#                                                                         str(end_goal_point.accelerations[4]))
#                    rospy.loginfo('interpolation : %s ! %s @ %s # %s $ %s  * %s ', str(end_goal_point.positions[0]),
#                                                                             str(end_goal_point.positions[1]),
#                                                                             str(end_goal_point.positions[2]),
#                                                                             str(end_goal_point.positions[3]),
#                                                                             str(end_goal_point.positions[4]),
#                                                                             str(end_goal_point.positions[5]))
                    rospy.loginfo('last error handle.')


            except Exception as e:
                rospy.logerr('Unexpected exception: %s', e)

        rospy.logdebug("Shutting down motion controller")

"""
AuboRobotSimulator

This class simulates an Aubo robot controller.  The simulator
adheres to the ROS-Industrial robot driver specification:

http://www.ros.org/wiki/Industrial/Industrial_Robot_Driver_Spec

TODO: Currently the simulator only supports the bare minimum motion interface.

TODO: Interfaces to add:
Joint streaming
All services
"""
class AuboRobotSimulatorNode():
    """
    Constructor of aubo robot simulator
    """
    def __init__(self):
        rospy.init_node('aubo_robot_simulator')

        # Class lock
        self.lock = threading.Lock()

        # Publish rate (hz)
        self.pub_rate = rospy.get_param('pub_rate', 50.0)
        rospy.loginfo("Setting publish rate (hz) based on parameter: %f", self.pub_rate)

        # Joint names
        def_joint_names = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6"]
        self.joint_names = rospy.get_param('controller_joint_names', def_joint_names)
        if len(self.joint_names) == 0:
            rospy.logwarn("Joint list is empty, did you set controller_joint_name?")
        rospy.loginfo("Simulating manipulator with %d joints: %s", len(self.joint_names), ", ".join(self.joint_names))

        # Setup initial joint positions
        num_joints = len(self.joint_names)

        # retrieve update rate
        external_axis_number = rospy.get_param('aubo_driver/external_axis_number', 0)  # set param to 0 to ignore interpolated motion
        rospy.loginfo("aubo_driver external_axis_number is: %d", external_axis_number)
        if external_axis_number > 0:
            motion_update_rate = 200
        else:
            motion_update_rate = 200

        self.motion_ctrl = MotionControllerSimulator(num_joints, update_rate=motion_update_rate)

        self.velocity_scale_factor = rospy.get_param('/aubo_controller/velocity_scale_factor', 1.0)
        rospy.loginfo("The velocity scale factor of the trajetory is: %f", self.velocity_scale_factor)

        # Published to joint states
        rospy.logdebug("Creating joint state publisher")
        self.joint_state_pub = rospy.Publisher('joint_states', JointState, queue_size=100)

        # Published to joint feedback
        rospy.logdebug("Creating joint feedback publisher")
        self.joint_feedback_pub = rospy.Publisher('feedback_states', FollowJointTrajectoryFeedback, queue_size=100)

        # Subscribe to a joint trajectory
        rospy.loginfo("Creating joint trajectory subscriber")
        self.joint_path_sub = rospy.Subscriber('joint_path_command', JointTrajectory, self.trajectory_callback)

        # Subscribe to a joint trajectory
        rospy.loginfo("Enable Switch")
        self.plan_type_sub = rospy.Subscriber('/aubo_driver/rib_status', Int32MultiArray, self.rib_status_callback)

        # JointStates timed task (started automatically)
        # period = rospy.Duration(1.0/self.pub_rate)
        # rospy.logdebug('Setting up publish worker with period (sec): %s', str(period.to_sec()))
        # rospy.Timer(period, self.publish_worker)

        self.EnableFlag = 1

        # GetRobotInfo service server and pre-cooked svc response
        self.get_robot_info_response = self._init_robot_info_response()
        self.svc_get_robot_info = rospy.Service('get_robot_info', GetRobotInfo, self.cb_svc_get_robot_info)

        rospy.loginfo("Clean up init")
        rospy.on_shutdown(self.motion_ctrl.shutdown)

    """
    Service callback for GetRobotInfo() service. Returns fake information.
    """
    def cb_svc_get_robot_info(self, req):
        # return cached response instance
        return self.get_robot_info_response

    """
    The publish worker is executed at a fixed rate.  This publishes the various
    state and status information to the action controller.
    """
    def publish_worker(self, event):
        pass
        # self.joint_state_publisher()
        # self.robot_status_publisher()         # robot_status message is published by aubo_driver

    """
    The joint state publisher publishes the current joint state and the current
    feedback state (as these are closely related)
    """
    def joint_state_publisher(self):
        if self.EnableFlag == 1 and self.motion_ctrl.positionUpdatedFlag == '1':
            try:
                joint_state_msg = JointState()
                joint_fb_msg = FollowJointTrajectoryFeedback()
                time = rospy.Time.now()

                with self.lock:
                    #Joint states
                    joint_state_msg.header.stamp = time
                    joint_state_msg.name = self.joint_names
                    joint_state_msg.position = self.motion_ctrl.get_joint_positions()
                    # self.joint_state_pub.publish(joint_state_msg)

                    #Joint feedback
                    joint_fb_msg.header.stamp = time
                    joint_fb_msg.joint_names = self.joint_names
                    joint_fb_msg.actual.positions = self.motion_ctrl.get_joint_positions()

                    # self.joint_feedback_pub.publish(joint_fb_msg)

            except Exception as e:
                rospy.loginfo('Unexpected exception in joint state publisher: %s', e)

    """
    The robot status publisher publishes the current simulated robot status.

    The following values are hard coded:
     - robot always in AUTO mode
     - drives always powered
     - motion always possible
     - robot never E-stopped
     - no error code
     - robot never in error

    The value of 'in_motion' is derived from the state of the MotionControllerSimulator.
    """
    def rib_status_callback(self, data):
        try:
            if  data.data[1] == 1:
                #self.EnableFlag = 1
                rospy.logdebug('True True %d',  self.EnableFlag)
            else:
                #self.EnableFlag = 0
                rospy.logdebug('False False %d',  self.EnableFlag)
            self.motion_ctrl.ribBufferSize = data.data[0]
            self.motion_ctrl.ControllerConnectedFlag = data.data[2]
            # rospy.loginfo('mode %d', data.data[1])

        except Exception as e:
            rospy.logerr('Unexpected exception: %s', e)

    """
    Trajectory subscription callback (gets called whenever a "joint_path_command" message is received).
    @param msg_in: joint trajectory message
    @type  msg_in: JointTrajectory
    """
    def trajectory_callback(self, msg_in):
        if (len(msg_in.points) == 0) or (self.EnableFlag == 0):
            # if the JointTrajectory is null or the robot is controlled by other controller.
            pass
        else:
            rospy.logdebug('handle joint_path_command')
            try:
                rospy.loginfo('Received trajectory with %s points, executing callback', str(len(msg_in.points)))

                if self.motion_ctrl.is_in_motion():
                    if len(msg_in.points) > 0:
                        rospy.logerr('Received trajectory while still in motion, trajectory splicing not supported')
                    else:
                        rospy.logdebug('Received empty trajectory while still in motion, stopping current trajectory')
                    # maybe no need to stop the controller, just feedback the status of the controller to outside!!
                    self.motion_ctrl.stop()

                else:
                    rospy.loginfo("start a new trajectory")
                    self.velocity_scale_factor = rospy.get_param('/aubo_controller/velocity_scale_factor', 1.0)
                    rospy.loginfo('The velocity scale factor is: %s', str(self.velocity_scale_factor))
                    new_traj = scale_trajectory_speed(msg_in, self.velocity_scale_factor)
                    self.motion_ctrl.pointCount = 0
                    self.motion_ctrl.pointAddFinish = 0
                    for point in new_traj.points:
                        # first remaps point to controller joint order, the add the point to the controller.
                        point = self._to_controller_order(msg_in.joint_names, point)
                        self.motion_ctrl.add_motion_waypoint(point)
                        self.motion_ctrl.pointCount += 1
                        #rospy.loginfo('T_p: %s', str(point.positions))
                        #rospy.loginfo('T_v: %s', str(point.velocities))
                        #rospy.loginfo('T_a: %s', str(point.accelerations))
                    self.motion_ctrl.pointAddFinish = 1
            except Exception as e:
                rospy.logerr('Unexpected exception: %s', e)

            rospy.logdebug('Exiting trajectory callback')

    """
    Remaps point to controller joint order

    @param point:  joint trajectory point
    @type  point:  JointTrajectoryPoint
    @return point: reorder point
    """
    def _to_controller_order(self, keys, point):
        pt_rtn = copy.deepcopy(point)
        pt_rtn.positions = self._remap_order(self.joint_names, keys, point.positions)
        pt_rtn.velocities = self._remap_order(self.joint_names, keys, point.velocities)
        pt_rtn.accelerations = self._remap_order(self.joint_names, keys, point.accelerations)
        return pt_rtn

    def _remap_order(self, ordered_keys, value_keys, values):
        #rospy.loginfo('remap order, ordered_keys: %s, value_keys: %s, values: %s', str(ordered_keys), str(value_keys), str(values))
        ordered_values = []

        ordered_values = [0]*len(ordered_keys)
        mapping = dict(zip(value_keys, values))
        #rospy.loginfo('maping: %s', str(mapping))

        for i in range(len(ordered_keys)):
            ordered_values[i] = mapping[ordered_keys[i]]
            pass

        return ordered_values

    """
    Constructs a GetRobotInfoResponse instance with either default data.
    """
    def _init_robot_info_response(self):
        if not rospy.has_param('~robot_info'):
            # if user did not provide data, we generate some
            import rospkg
            rp = rospkg.RosPack()
            irs_version = rp.get_manifest('industrial_robot_simulator').version
            robot_info = dict(
                controller=dict(
                    model='Aubo Robot Simulator Controller',
                    serial_number='0123456789',
                    sw_version=irs_version),
                robots=[
                    dict(
                        model='Aubo Robot Simulator Manipulator',
                        serial_number='9876543210',
                        sw_version=irs_version)
                ])
        else:
            # otherwise use only the data user has provided (and nothing more)
            robot_info = rospy.get_param('~robot_info')

        resp = GetRobotInfoResponse()
        resp.controller = DeviceInfo(**robot_info['controller'])

        # add info on controlled robot / motion group
        if len(robot_info['robots']) > 0:
            robot = robot_info['robots'][0]
            resp.robots.append(DeviceInfo(**robot))

        if len(robot_info['robots']) > 1:
            # simulator simulates a single robot / motion group
            rospy.logwarn("Multiple robots / motion groups defined in "
                "'robot_info' parameter, ignoring all but first element")

        # always successfull
        resp.code.val = ServiceReturnCode.SUCCESS
        return resp

if __name__ == '__main__':
    try:
        rospy.loginfo('Starting aubo_controller_simulator')
        controller = AuboRobotSimulatorNode()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
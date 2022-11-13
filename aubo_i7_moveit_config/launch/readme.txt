moveit_planning_execution.launch 是新增文件，从i5中copy过来

aubo_i7_moveit_controller_manager.launch.xml，aubo_i7_moveit_controller_manager.launch 是新增文件

------------------------------------
move_group.launch （新增了第一行<include file="$(find aubo_i7_moveit_config)/launch/planning_context.launch" />）, 修改前为

<launch>
  <include file="$(find aubo_i7_moveit_config)/launch/planning_context.launch" />
  
  <!-- GDB Debug Option -->
  <arg name="debug" default="false" />
  <arg unless="$(arg debug)" name="launch_prefix" value="" />
  <arg     if="$(arg debug)" name="launch_prefix"
           value="gdb -x $(dirname)/gdb_settings.gdb --ex run --args" />

  <!-- Verbose Mode Option -->
  <arg name="info" default="$(arg debug)" />
  <arg unless="$(arg info)" name="command_args" value="" />
  <arg     if="$(arg info)" name="command_args" value="--debug" />

  <!-- move_group settings -->
  <arg name="pipeline" default="ompl" />
  <arg name="allow_trajectory_execution" default="true"/>
  <arg name="moveit_controller_manager" default="simple" />
  <arg name="fake_execution_type" default="interpolate"/>
  <arg name="max_safe_path_cost" default="1"/>
  <arg name="publish_monitored_planning_scene" default="true"/>

  <arg name="capabilities" default=""/>
  <arg name="disable_capabilities" default=""/>
  <!-- load these non-default MoveGroup capabilities (space seperated) -->
  <!--
  <arg name="capabilities" value="
                a_package/AwsomeMotionPlanningCapability
                another_package/GraspPlanningPipeline
                " />
  -->

  <!-- inhibit these default MoveGroup capabilities (space seperated) -->
  <!--
  <arg name="disable_capabilities" value="
                move_group/MoveGroupKinematicsService
                move_group/ClearOctomapService
                " />
  -->

  <arg name="load_robot_description" default="false" />
  <!-- load URDF, SRDF and joint_limits configuration -->
  <include file="$(dirname)/planning_context.launch">
    <arg name="load_robot_description" value="$(arg load_robot_description)" />
  </include>

  <!-- Planning Pipelines -->
  <group ns="move_group/planning_pipelines">

    <!-- OMPL -->
    <include file="$(dirname)/planning_pipeline.launch.xml">
      <arg name="pipeline" value="ompl" />
    </include>

    <!-- CHOMP -->
    <include file="$(dirname)/planning_pipeline.launch.xml">
      <arg name="pipeline" value="chomp" />
    </include>

    <!-- Pilz Industrial Motion -->
    <include file="$(dirname)/planning_pipeline.launch.xml">
      <arg name="pipeline" value="pilz_industrial_motion_planner" />
    </include>

    <!-- Support custom planning pipeline -->
    <include if="$(eval arg('pipeline') not in ['ompl', 'chomp', 'pilz_industrial_motion_planner'])"
             file="$(dirname)/planning_pipeline.launch.xml">
      <arg name="pipeline" value="$(arg pipeline)" />
    </include>
  </group>

  <!-- Trajectory Execution Functionality -->
  <include ns="move_group" file="$(dirname)/trajectory_execution.launch.xml" if="$(arg allow_trajectory_execution)">
    <arg name="moveit_manage_controllers" value="true" />
    <arg name="moveit_controller_manager" value="$(arg moveit_controller_manager)" />
    <arg name="fake_execution_type" value="$(arg fake_execution_type)" />
  </include>

  <!-- Sensors Functionality -->
  <include ns="move_group" file="$(dirname)/sensor_manager.launch.xml" if="$(arg allow_trajectory_execution)">
    <arg name="moveit_sensor_manager" value="aubo_i7" />
  </include>

  <!-- Start the actual move_group node/action server -->
  <node name="move_group" launch-prefix="$(arg launch_prefix)" pkg="moveit_ros_move_group" type="move_group" respawn="false" output="screen" args="$(arg command_args)">
    <!-- Set the display variable, in case OpenGL code is used internally -->
    <env name="DISPLAY" value="$(optenv DISPLAY :0)" />

    <param name="allow_trajectory_execution" value="$(arg allow_trajectory_execution)"/>
    <param name="sense_for_plan/max_safe_path_cost" value="$(arg max_safe_path_cost)"/>
    <param name="default_planning_pipeline" value="$(arg pipeline)" />
    <param name="capabilities" value="$(arg capabilities)" />
    <param name="disable_capabilities" value="$(arg disable_capabilities)" />

    <!-- do not copy dynamics information from /joint_states to internal robot monitoring
         default to false, because almost nothing in move_group relies on this information -->
    <param name="monitor_dynamics" value="false" />

    <!-- Publish the planning scene of the physical robot so that rviz plugin can know actual robot -->
    <param name="planning_scene_monitor/publish_planning_scene" value="$(arg publish_monitored_planning_scene)" />
    <param name="planning_scene_monitor/publish_geometry_updates" value="$(arg publish_monitored_planning_scene)" />
    <param name="planning_scene_monitor/publish_state_updates" value="$(arg publish_monitored_planning_scene)" />
    <param name="planning_scene_monitor/publish_transforms_updates" value="$(arg publish_monitored_planning_scene)" />
  </node>

</launch>


----------------------------------------------------
moveit_rviz.launch 修改前为
<launch>

  <arg name="debug" default="false" />
  <arg unless="$(arg debug)" name="launch_prefix" value="" />
  <arg     if="$(arg debug)" name="launch_prefix" value="gdb --ex run --args" />

  <arg name="rviz_config" default="" />
  <arg     if="$(eval rviz_config=='')" name="command_args" value="" />
  <arg unless="$(eval rviz_config=='')" name="command_args" value="-d $(arg rviz_config)" />

  <node name="$(anon rviz)" launch-prefix="$(arg launch_prefix)" pkg="rviz" type="rviz" respawn="false"
        args="$(arg command_args)" output="screen">
  </node>

</launch>	
-------------------------
chomp_planning_pipeline.launch.xml 修改前为
<launch>
  <arg name="start_state_max_bounds_error" default="0.1" />
  <arg name="jiggle_fraction" default="0.05" />
  <!-- The request adapters (plugins) used when planning. ORDER MATTERS! -->
  <arg name="planning_adapters"
       default="default_planner_request_adapters/LimitMaxCartesianLinkSpeed
                default_planner_request_adapters/AddTimeParameterization
                default_planner_request_adapters/ResolveConstraintFrames
                default_planner_request_adapters/FixWorkspaceBounds
                default_planner_request_adapters/FixStartStateBounds
                default_planner_request_adapters/FixStartStateCollision
                default_planner_request_adapters/FixStartStatePathConstraints"
                />

  <param name="planning_plugin" value="chomp_interface/CHOMPPlanner" />
  <param name="request_adapters" value="$(arg planning_adapters)" />
  <param name="start_state_max_bounds_error" value="$(arg start_state_max_bounds_error)" />
  <param name="jiggle_fraction" value="$(arg jiggle_fraction)" />

  <!-- Add MoveGroup capabilities specific to this pipeline -->
  <!-- <param name="capabilities" value="" /> -->

  <rosparam command="load" file="$(find aubo_i7_moveit_config)/config/chomp_planning.yaml" />
</launch>
-----------------
trajectory_execution.launch.xml 修改前为
<launch>
  <!-- This file summarizes all settings required for trajectory execution  -->

  <!-- Define moveit controller manager plugin: fake, simple, or ros_control -->
  <arg name="moveit_controller_manager" />
  <arg name="fake_execution_type" default="interpolate" />

  <!-- Flag indicating whether MoveIt is allowed to load/unload  or switch controllers -->
  <arg name="moveit_manage_controllers" default="true"/>
  <param name="moveit_manage_controllers" value="$(arg moveit_manage_controllers)"/>

  <!-- When determining the expected duration of a trajectory, this multiplicative factor is applied to get the allowed duration of execution -->
  <param name="trajectory_execution/allowed_execution_duration_scaling" value="1.2"/> <!-- default 1.2 -->
  <!-- Allow more than the expected execution time before triggering a trajectory cancel (applied after scaling) -->
  <param name="trajectory_execution/allowed_goal_duration_margin" value="0.5"/> <!-- default 0.5 -->
  <!-- Allowed joint-value tolerance for validation that trajectory's first point matches current robot state -->
  <param name="trajectory_execution/allowed_start_tolerance" value="0.01"/> <!-- default 0.01 -->

  <!-- We use pass_all_args=true here to pass fake_execution_type, which is required by fake controllers, but not by real-robot controllers.
       As real-robot controller_manager.launch files shouldn't be required to define this argument, we use the trick of passing all args. -->
  <include file="$(dirname)/$(arg moveit_controller_manager)_moveit_controller_manager.launch.xml" pass_all_args="true" />

</launch>




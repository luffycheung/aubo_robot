controllers.yaml, joint_names.yaml 是新增文件

ros_controller.ymal 修改前为

aubo_i7_controller:
  type: position_controllers/JointTrajectoryController
  joints:
    - shoulder_joint
    - upperArm_joint
    - foreArm_joint
    - wrist1_joint
    - wrist2_joint
    - wrist3_joint
  gains:
    shoulder_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
    upperArm_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
    foreArm_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
    wrist1_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
    wrist2_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
    wrist3_joint:
      p: 100
      d: 1
      i: 1
      i_clamp: 1
      
     

# Commands

---

## TELEOPERATE

### MONO Rebot + pico
```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30
```

---

## RECORD

### MONO Rebot + pico
```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --dataset.repo_id=etince11e/Object-Storage \
  --dataset.single_task="Put all the objects on the table into the box." \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=300 \
  --dataset.reset_time_s=60 \
  --dataset.fps=30 \
  --dataset.push_to_hub=true \
  --resume=true \
  --dataset.root=/home/jeff/.cache/huggingface/lerobot/etince11e/Object-Storage
```

```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --dataset.repo_id=etince11e/Tool-Storage \
  --dataset.single_task="Put all the tools on the table back into their correct places in the toolbox." \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=300 \
  --dataset.reset_time_s=60 \
  --dataset.fps=30 \
  --dataset.rgb_encoder.vcodec=h264 \
  --dataset.rgb_encoder.crf=23 \
  --dataset.rgb_encoder.preset=ultrafast \
  --dataset.video_encoding_batch_size=0 \
  --dataset.push_to_hub=false \
  --resume=false \
  --dataset.root=~/.cache/huggingface/lerobot/etince11e/Tool-Storage
```

```bash
lerobot-record \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --dataset.repo_id=etince11e/Object-Storage \
  --dataset.single_task="Put all the objects on the table into the box." \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=300 \
  --dataset.reset_time_s=60 \
  --dataset.fps=30 \
  --dataset.rgb_encoder.vcodec=h264 \
  --dataset.rgb_encoder.crf=23 \
  --dataset.rgb_encoder.preset=ultrafast \
  --dataset.video_encoding_batch_size=0 \
  --dataset.push_to_hub=true \
  --resume=false \
  --dataset.root=~/.cache/huggingface/lerobot/etince11e/Object-Storage
```

---

## TRAIN

### MONO Rebot + pico
```bash
lerobot-train \
  --dataset.repo_id=etince11e/Object-Storage \
  --dataset.root=/home/jeff/.cache/huggingface/lerobot/etince11e/Object-Storage \
  --dataset.revision=v0.1.0 \
  --dataset.streaming=false \
  --policy.type=act \
  --output_dir=outputs/train/act_Object_Storage_joint \
  --job_name=act_rebot_task \
  --policy.device=cuda \
  --wandb.enable=true \
  --wandb.project=act_Object_Storage_joint \
  --policy.push_to_hub=false \
  --steps=50000 \
  --save_freq=10000 \
  --batch_size=8
```


#### 从第 30000 步继续训练，并把总训练步数延长到 100000：
```bash
lerobot-train \
  --config_path=outputs/train/act_Object_Storage_joint/checkpoints/030000/pretrained_model/train_config.json \
  --resume=true \
  --steps=100000 \
  --save_freq=10000
```

#### 从最新 checkpoint 继续：
```bash
lerobot-train \
  --config_path=outputs/train/act_Object_Storage_joint/checkpoints/last/pretrained_model/train_config.json \
  --resume=true \
  --steps=100000
  --save_freq=10000
```

#### 加载某个 checkpoint 的权重、重新开始一个新的训练任务：
```bash
lerobot-train \
  --dataset.repo_id=etince11e/Object-Storage \
  --dataset.root=/home/jeff/.cache/huggingface/lerobot/etince11e/Object-Storage \
  --policy.path=outputs/train/act_Object_Storage_joint/checkpoints/030000/pretrained_model \
  --output_dir=outputs/train/act_Object_Storage_joint_from_030000 \
  --policy.device=cuda \
  --steps=50000 \
  --batch_size=8
```


---

## inference

### MONO Rebot + pico
```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=outputs/train/act_Object_Storage_joint/checkpoints/050000/pretrained_model \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --device=cuda \
  --fps=30 \
  --interactive=true \
  --return_to_initial_position=true
```

---

## debug

### visualize camera
```bash
ffplay -f v4l2 -video_size 640x480 -framerate 30 /dev/video2
```


### watch utils GPU
```bash
watch -n 1 nvidia-smi
```

# Commands

-------------------------------------
TELEOPERATE
-------------------------------------

## MONO Rebot + pico
```bash
lerobot-teleoperate \
  --robot.type=rebot_rs_follower \
  --robot.id=rebot_rs \
  --teleop.type=pico4 \
  --teleop.id=pico4 \
  --fps=30
```





-------------------------------------
RECORD
-------------------------------------

## MONO Rebot + pico
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
  --dataset.push_to_hub=true \
  --resume=false \
  --dataset.root=~/.cache/huggingface/lerobot/etince11e/Object-Storage
```
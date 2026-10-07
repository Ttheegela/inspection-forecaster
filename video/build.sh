#!/bin/bash
# Stitch frames/NN.png + audio/NN.mp3 -> ../demo_video.mp4 (each scene = audio + 0.6 s)
set -e
cd "$(dirname "$0")"; FF=/opt/homebrew/bin/ffmpeg; mkdir -p clips; : > clips/list.txt
for a in audio/*.mp3; do
  n=$(basename $a .mp3)
  d=$(/opt/homebrew/bin/ffprobe -v error -show_entries format=duration -of csv=p=0 $a)
  t=$(echo "$d + 0.6" | bc)
  $FF -y -loglevel error -loop 1 -framerate 30 -i frames/$n.png -i $a -t $t \
    -af "apad,aresample=48000" -c:v libx264 -tune stillimage -pix_fmt yuv420p -r 30 \
    -c:a aac -b:a 192k -ac 2 clips/$n.mp4
  echo "file '$n.mp4'" >> clips/list.txt
done
$FF -y -loglevel error -f concat -safe 0 -i clips/list.txt -c copy -movflags +faststart ../demo_video.mp4

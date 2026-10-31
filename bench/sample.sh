#!/bin/bash
# usage: sample.sh out.csv  -- samples every 5s until killed
echo "ts,swap_used_mb,free_pct,h3c_rss_mb,gpu_util" > "$1"
while true; do
  sw=$(sysctl -n vm.swapusage | awk '{gsub("M","",$6);print $6}')
  fp=$(memory_pressure | awk '/free percentage/{gsub("%","",$5);print $5}')
  rss=$(ps -o rss= -p $(pgrep -x H3cApp) | awk '{printf "%d",$1/1024}')
  gpu=$(ioreg -r -d 1 -c IOAccelerator | grep -o '"Device Utilization %"=[0-9]*' | head -1 | cut -d= -f2)
  echo "$(date +%s),$sw,$fp,$rss,$gpu" >> "$1"; sleep 5
done

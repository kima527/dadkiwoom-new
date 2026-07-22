import io

with io.open('data_manager.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'self.last_tick_price = 0.0' in line:
        new_lines.append(line)
        new_lines.append('        import time\n')
        new_lines.append('        import threading\n')
        new_lines.append('        self.tick_timestamps = deque(maxlen=20)\n')
        continue
    
    if 'self.raw_tick_buffer.append(tick_data)' in line:
        new_lines.append(line)
        new_lines.append('        import time\n')
        new_lines.append('        self.tick_timestamps.append(time.time())\n')
        continue
        
    new_lines.append(line)

new_lines.append('\n    def get_tick_velocity(self) -> float:\n')
new_lines.append('        """\n')
new_lines.append('        Return time difference between first and last tick in recent 20 ticks.\n')
new_lines.append('        """\n')
new_lines.append('        if len(self.tick_timestamps) < 20:\n')
new_lines.append('            return 999.0\n')
new_lines.append('        return self.tick_timestamps[-1] - self.tick_timestamps[0]\n')

with io.open('data_manager.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Done!')

"""UI-owned CAVA reader. Monitors audio output; never contacts Pandora."""
import asyncio
from pathlib import Path
import shutil
import tempfile
from rich.text import Text
from textual import work
from textual.widgets import Static

BARS = 48
CONFIG = f"""[general]
framerate = 30
bars = {BARS}
autosens = 1
[input]
method = pipewire
source = auto
[output]
method = raw
raw_target = /dev/stdout
data_format = binary
bit_format = 8bit
channels = mono
[smoothing]
noise_reduction = 75
"""


def spectrum_lines(values, width, height):
    """Fit real amplitudes to terminal cells, using eighth-block vertical steps."""
    if width < 1 or height < 1:
        return []
    count = min(len(values), max(1, width // 2))
    if not count:
        return [' ' * width for _ in range(height)]
    levels = [max(values[i * len(values) // count:(i + 1) * len(values) // count])
              * height * 8 // 255 for i in range(count)]
    gap = ' ' if width >= count * 2 else ''
    chars = ' ▁▂▃▄▅▆▇█'
    lines = []
    for row in range(height - 1, -1, -1):
        line = gap.join(chars[max(0, min(8, level - row * 8))] for level in levels)
        lines.append(line.center(width))
    return lines


class Spectrum(Static):
    def __init__(self, enabled=True, **kwargs):
        super().__init__(**kwargs)
        self.enabled = enabled
        self.values = bytes(BARS)
        self.process = None
        self.failure = ''
        self.frames = 0
        self.directory = None
        self.capture = None

    def on_mount(self):
        if self.enabled:
            self.capture = self.listen()

    @work(exclusive=True)
    async def listen(self):
        if not shutil.which('cava'):
            self.failure = 'Install CAVA to enable the audio spectrum'
            self.refresh()
            return
        self.directory = tempfile.TemporaryDirectory(prefix='pandora-spectrum-')
        path = Path(self.directory.name) / 'config'
        path.write_text(CONFIG)
        try:
            self.process = await asyncio.create_subprocess_exec('cava', '-p', str(path),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            while True:
                self.values = await self.process.stdout.readexactly(BARS)
                self.frames += 1
                self.refresh()
        except (OSError, asyncio.IncompleteReadError):
            self.failure = 'Audio spectrum unavailable · playback still works'
            self.refresh()
        finally:
            await self.stop_process()

    async def stop_process(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.directory:
            self.directory.cleanup()
            self.directory = None

    async def on_unmount(self):
        if self.capture:
            self.capture.cancel()
        await self.stop_process()

    def render(self):
        if self.failure:
            return Text(self.failure, style='dim', overflow='ellipsis', no_wrap=True)
        return Text('\n'.join(spectrum_lines(self.values, self.size.width, self.size.height)))

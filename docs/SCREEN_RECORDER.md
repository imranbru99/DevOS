# Screen Recorder and clip editor

Start Screen Recorder from the application menu. Choose microphone, system audio
or muted capture. **Listen to input** starts a live logarithmic loudness meter;
turn it off to stop monitoring. Recording automatically starts the chosen input
meter and shows a small always-on-top Stop & save toolbar plus a tray indicator.
The meter shows signal level in dBFS, with a red warning near clipping. It is not
an input gain control: adjust microphone volume in Sound Settings if needed.
When capture ends, an FFmpeg worker saves MP4 or WebM without blocking the window.
Source recordings remain available; failed muxing preserves captured audio too.

**Edit recording / Open video** opens the last recording, or a file chooser when
there is no last recording. Times in the clip editor refer to the original video:

- Trim selected replaces a clip with the selected time range.
- Copy selection to end appends another copy of that source time range.
- Cut selection removes the range from the selected clip, retaining its two sides.
- Remove clip removes one whole entry. Clips export in list order.
- Audio options keep, remove, replace or mix the original audio. Choose a voice
  or music file for replacement/mixing. Short audio is padded with silence; long
  audio is trimmed to the video length. Mixing normalizes the two tracks.

Export writes a separate H.264/AAC MP4; silent exports have no audio track.
Existing output files and the source file cannot be overwritten. Export runs in
the background and reports errors; the editor stays open until it finishes.
This is a small clip editor, not a full multi-track video-production timeline.

Synthetic tests exercise real MP4/WebM muxing, trim/cut/copy exports, audio modes,
silent input, path handling and original-file preservation. Live Wayland capture,
microphone permissions and hardware input levels require a desktop-session test.

# MoviePilot Plugins

MoviePilot plugins by luyang1104.

## CloudStrm

CloudStrm monitors a CD2-mounted directory and generates STRM files that point to OpenList files. It also supports subtitles and common sidecar files such as NFO, posters, backdrops, and JSON files, then refreshes configured Emby libraries after generation.

Features:

- Monitor created, modified, moved, and deleted files.
- Wait for files to become stable before processing them.
- Generate STRM files using the configured OpenList URL template.
- Copy subtitles and related NFO/image/JSON files.
- Optional cleanup of generated files after source deletion.
- Refresh one or more configured Emby servers.
- Keep the existing `/strm` command for manual generation, including category paths such as `/strm foreign-movies`.
- Run a full scan with the `CloudStrmCompanion` command.

## MoviePilot subscription

```text
https://raw.githubusercontent.com/luyang1104/MoviePilot-Plugins/main/package.v2.json
```

Add the URL above to MoviePilot's plugin repository subscription settings.

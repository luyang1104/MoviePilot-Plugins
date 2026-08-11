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
- Run a full scan with the `CloudStrmHelper` command.

## MoviePilot market source

Subscribe to the repository itself in MoviePilot's plugin market settings:

```text
https://github.com/luyang1104/MoviePilot-Plugins
```

Do not use the raw `package.json` URL as the market source. MoviePilot reads
`package.v3.json` for v3, `package.v2.json` for v2, and the matching
`plugins.v3/` or `plugins.v2/` directory automatically.

For MoviePilot v3, add the repository to `PLUGIN_MARKET` together with any
existing sources, separated by commas, then refresh the plugin market:

```text
https://github.com/jxxghp/MoviePilot-Plugins,https://github.com/luyang1104/MoviePilot-Plugins
```

The current plugin ID is `CloudStrmHelper` and its display name is
`CloudStrm`. Future plugins can be added to this same repository by adding
their metadata to the package index and their code under the matching
`plugins.v3/<plugin-id>/` and/or `plugins.v2/<plugin-id>/` directory.

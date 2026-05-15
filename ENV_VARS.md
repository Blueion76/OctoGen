# 📋 Environment Variables Reference

Complete reference for all OctoGen environment variables.

---

## 🔴 Required Variables

These variables **must** be set for OctoGen to work.

### NAVIDROME_URL
**Description**: URL of your Navidrome server  
**Format**: `http://hostname:port` or `https://hostname:port`  
**Examples**:
```bash
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_URL=http://navidrome:4533
NAVIDROME_URL=https://music.example.com
```
**Notes**:
- Do not include trailing slash
- If in Docker, can use service name: `http://navidrome:4533`
- If accessing host from container: `http://host.docker.internal:4533`

---

### NAVIDROME_USER
**Description**: Navidrome username  
**Format**: String  
**Example**:
```bash
NAVIDROME_USER=admin
```

---

### NAVIDROME_PASSWORD
**Description**: Navidrome password  
**Format**: String  
**Example**:
```bash
NAVIDROME_PASSWORD=your_secure_password
```
**Notes**:
- Password is sent securely via Subsonic API (MD5 token with salt)
- Not stored in plain text in logs

---

### OCTOFIESTA_ENABLED
**Description**: Enable Octo-Fiesta downloads for missing tracks
**Default**: `true`
**Options**: `true`, `false`
**Example**:
```bash
OCTOFIESTA_ENABLED=false
```
**Notes**:
- When `false`, OctoGen runs in local-only mode: missing tracks are excluded from playlists and `OCTOFIESTA_URL` is not required.
- One summary line per run reports the skip count.

---

### OCTOFIESTA_URL
**Description**: URL of your Octo-Fiesta server  
**Format**: `http://hostname:port`  
**Examples**:
```bash
OCTOFIESTA_URL=http://192.168.1.100:8080
OCTOFIESTA_URL=http://octo-fiesta:8080
```
**Notes**:
- Required for automatic downloading of missing tracks
- Uses same Navidrome credentials
- Required only when `OCTOFIESTA_ENABLED=true` (the default).

---

### AI_API_KEY
**Description**: API key for your LLM provider (LLM-based recommendations)  
**Type**: String  
**Required**: No (optional if AudioMuse-AI, Last.fm, or ListenBrainz is enabled)  
**Examples**:
```bash
# Gemini
AI_API_KEY=AIzaSyABC123xyz...

# Groq
AI_API_KEY=gsk_abc123xyz...

# OpenAI
AI_API_KEY=sk-abc123xyz...

# Ollama (local)
AI_API_KEY=ollama
```
**Get Keys**:
- **Gemini**: https://aistudio.google.com/apikey (free tier)
- **Groq**: https://console.groq.com (free tier)
- **OpenAI**: https://platform.openai.com/api-keys
- **Ollama**: Use `ollama` as the key

**Notes**:
- **Optional**: Not required if you configure AudioMuse-AI, Last.fm, ListenBrainz, Spotify Import, or Deezer Import
- At least one music source must be configured (LLM, AudioMuse, Last.fm, ListenBrainz, Spotify Import, or Deezer Import)
- Keep API keys secure and never commit to version control

---

## 🟡 LLM Configuration (Optional)

### AI_MODEL
**Description**: LLM model to use for recommendations  
**Default**: `gemini-2.5-flash`  
**Examples**:
```bash
# Gemini
AI_MODEL=gemini-2.5-flash
AI_MODEL=gemini-2.0-flash-exp

# Groq
AI_MODEL=llama-3.3-70b-versatile
AI_MODEL=mixtral-8x7b-32768

# OpenAI
AI_MODEL=gpt-4o
AI_MODEL=gpt-4o-mini

# Ollama
AI_MODEL=llama3.2
AI_MODEL=mixtral
```

---

### AI_BACKEND
**Description**: LLM backend to use  
**Default**: `gemini`  
**Options**: `gemini`, `openai`  
**Examples**:
```bash
# For Gemini (native SDK with caching)
AI_BACKEND=gemini

# For OpenAI, Groq, Ollama, OpenRouter (OpenAI-compatible)
AI_BACKEND=openai
```
**Notes**:
- `gemini`: Uses native Gemini SDK with context caching (more efficient)
- `openai`: Uses OpenAI library (compatible with many providers)

---

### AI_BASE_URL
**Description**: Custom API endpoint URL  
**Default**: None (uses provider default)  
**Examples**:
```bash
# Groq
AI_BASE_URL=https://api.groq.com/openai/v1

# Ollama
AI_BASE_URL=http://host.docker.internal:11434/v1

# OpenRouter
AI_BASE_URL=https://openrouter.ai/api/v1

# Custom OpenAI-compatible
AI_BASE_URL=https://api.custom.com/v1
```
**Notes**:
- Only used when `AI_BACKEND=openai`
- Leave empty for official OpenAI API

---

### AI_MAX_CONTEXT_SONGS
**Description**: Maximum number of songs to send to the LLM for context  
**Default**: `500`  
**Range**: `100` to `1000`  
**Example**:
```bash
AI_MAX_CONTEXT_SONGS=500
```
**Notes**:
- Higher = more accurate but more expensive
- Lower = cheaper but less personalized

---

### AI_MAX_OUTPUT_TOKENS
**Description**: Maximum tokens the LLM can generate in a response  
**Default**: `8192`  
**Range**: `8192` to `65535`  
**Example**:
```bash
AI_MAX_OUTPUT_TOKENS=8192
```

---

### AI_REQUEST_TIMEOUT
**Description**: Timeout in seconds for each AI API request. Increase this value if you experience timeout errors, especially with slower models or high `AI_MAX_OUTPUT_TOKENS` values.  
**Default**: `300`  
**Minimum**: `30`  
**Example**:
```bash
# Default (5 minutes)
AI_REQUEST_TIMEOUT=300

# Increase for large outputs or slow connections
AI_REQUEST_TIMEOUT=600
```

**Notes**:
- Applies to OpenAI-compatible backends (`openai`, `groq`, `mistral`, `ollama`, custom)
- On timeout, OctoGen will retry up to 3 times with exponential backoff before failing
- If you consistently hit timeouts, also consider reducing `AI_MAX_OUTPUT_TOKENS`

---

### SEED_FALLBACK_MIN
**Description**: When the user has fewer than this many starred songs, OctoGen augments the AI seed with songs from the user's most-played albums. This avoids `min_total_token_count` errors from the Gemini context cache (1024-token floor) for users who don't favorite many songs.
**Default**: `50`
**Example**:
```bash
SEED_FALLBACK_MIN=50
```
**Notes**:
- Set to `0` to disable the fallback entirely (only starred songs will seed the LLM)

---

### SEED_FALLBACK_TARGET
**Description**: Target total seed size after augmenting with most-played albums. Augmentation stops once the seed reaches this size.
**Default**: `500`
**Example**:
```bash
SEED_FALLBACK_TARGET=500
```

---

### SEED_FALLBACK_ALBUM_COUNT
**Description**: Number of most-played albums to pull from Subsonic `getAlbumList2?type=frequent` when augmenting the seed.
**Default**: `100`
**Example**:
```bash
SEED_FALLBACK_ALBUM_COUNT=100
```

---

## 🕐 Scheduling Configuration (Optional)

### SCHEDULE_CRON
**Description**: Cron expression for automatic scheduling  
**Default**: None (manual run)  
**Format**: Standard cron expression  
**Examples**:
```bash
# Daily at 2 AM
SCHEDULE_CRON=0 6 * * *

# Twice daily (2 AM and 6 PM)
SCHEDULE_CRON=0 6,18 * * *

# Every 12 hours
SCHEDULE_CRON=0 */12 * * *

# Every 6 hours
SCHEDULE_CRON=0 */6 * * *

# Weekly on Sunday at 3 AM
SCHEDULE_CRON=0 3 * * 0

# Every Monday at 9 AM
SCHEDULE_CRON=0 9 * * 1

# Every 30 minutes (testing)
SCHEDULE_CRON=*/30 * * * *

# Manual run (no scheduling)
SCHEDULE_CRON=manual
```
**Cron Format**:
```
* * * * *
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7, 0 and 7 = Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```
**Notes**:
- Requires `croniter` Python package (included in Docker image)
- Container stays running and executes on schedule
- Shows countdown in logs: "⏰ Next run in 3.5 hours"
- To disable: Leave unset or use `manual`, `off`, `false`, `no`, `disabled`
- Test expressions at: https://crontab.guru
- **Recommended**: Set with `TZ` variable for correct timezone

**How It Works**:
1. When `SCHEDULE_CRON` is set, container stays running
2. Calculates next run time from cron expression
3. Waits until that time (showing countdown)
4. Executes OctoGen
5. Repeats forever (or until stopped)
6. On error: logs error and continues to next scheduled run

---

### TZ
**Description**: Timezone for scheduled runs  
**Default**: `UTC`  
**Format**: IANA timezone name  
**Examples**:
```bash
# United States
TZ=America/New_York      # Eastern Time
TZ=America/Chicago       # Central Time
TZ=America/Denver        # Mountain Time
TZ=America/Los_Angeles   # Pacific Time
TZ=America/Phoenix       # Arizona (no DST)
TZ=America/Anchorage     # Alaska
TZ=Pacific/Honolulu      # Hawaii

# Europe
TZ=Europe/London         # UK
TZ=Europe/Paris          # France/Central Europe
TZ=Europe/Berlin         # Germany
TZ=Europe/Rome           # Italy
TZ=Europe/Madrid         # Spain
TZ=Europe/Amsterdam      # Netherlands

# Asia
TZ=Asia/Tokyo            # Japan
TZ=Asia/Shanghai         # China
TZ=Asia/Seoul            # South Korea
TZ=Asia/Singapore        # Singapore
TZ=Asia/Dubai            # UAE
TZ=Asia/Kolkata          # India

# Australia
TZ=Australia/Sydney      # East Coast
TZ=Australia/Melbourne   # Victoria
TZ=Australia/Perth       # West Coast

# Other
TZ=UTC                   # Universal (default)
```
**Notes**:
- **Important**: Set this with `SCHEDULE_CRON` for correct local times
- Without `TZ`, all times are UTC
- List all timezones: `timedatectl list-timezones`
- Docker uses container timezone, not host timezone
- Visible in logs: "Timezone: America/Chicago"

**Example - Schedule 2 AM Local Time**:
```bash
# Wrong (runs at 2 AM UTC, not your local time)
SCHEDULE_CRON=0 6 * * *

# Right (runs at 2 AM Chicago time)
SCHEDULE_CRON=0 6 * * *
TZ=America/Chicago
```

---

### MIN_RUN_INTERVAL_HOURS
**Description**: Minimum hours between runs when primary services (LLM/AudioMuse) succeed  
**Default**: `6`  
**Range**: `1` to `48`  
**Example**:
```bash
MIN_RUN_INTERVAL_HOURS=6
```
**Notes**:
- Applied when the LLM or AudioMuse playlists are successfully generated
- **Only used in manual mode** (when `SCHEDULE_CRON` is not set or set to `manual`)
- Prevents duplicate runs from container restarts or manual triggers
- In scheduled mode (with `SCHEDULE_CRON`), cooldown is automatically calculated from cron expression
- Automatic cooldown = 90% of detected cron interval (e.g., 6h cron → 5.4h cooldown)
- Set lower (e.g., 4h) if you want to allow more frequent manual runs
- Set higher (e.g., 12h) if you want to enforce longer gaps between runs

**How It Works**:
- **Scheduled mode** (`SCHEDULE_CRON=0 */6 * * *`):
  - Automatically detects 6h interval → uses 5.4h cooldown (90%)
  - Prevents container restarts or manual triggers within 5.4h of last run
  - Scheduled runs proceed normally every 6h
- **Manual mode** (no `SCHEDULE_CRON`):
  - Uses `MIN_RUN_INTERVAL_HOURS` as cooldown (default: 6h)
  - Prevents running more than once per 6h
  - Good for manual docker exec or restart protection

**Examples**:
```bash
# Cron every 6 hours (auto cooldown: 5.4h)
SCHEDULE_CRON=0 */6 * * *
# MIN_RUN_INTERVAL_HOURS is ignored

# Manual mode with 6h cooldown
# MIN_RUN_INTERVAL_HOURS not set (uses default 6h)
# or explicitly:
MIN_RUN_INTERVAL_HOURS=6

# Manual mode with custom 4h cooldown
MIN_RUN_INTERVAL_HOURS=4
```

---

### MIN_RUN_INTERVAL_HOURS
**Description**: Minimum hours between runs in manual mode (no SCHEDULE_CRON)  
**Default**: `6`  
**Range**: `0.5` to `24`  
**Example**:
```bash
MIN_RUN_INTERVAL_HOURS=6
```
**Notes**:
- Only applies when SCHEDULE_CRON is not set or set to "manual"
- In scheduled mode (with SCHEDULE_CRON), uses 90% of cron interval instead
- All services respect this cooldown period equally
- Prevents duplicate runs after successful completion
- System checks `octogen_last_run.json` for last run timestamp

**Cooldown Logic**:
- **Scheduled mode**: Cooldown = 90% of detected cron interval
- **Manual mode**: Cooldown = MIN_RUN_INTERVAL_HOURS
- Applied uniformly regardless of which services succeeded/failed
- Ensures schedule is properly respected

---

**Why This Matters**:
- **AI rate limits** don't prevent external service refreshes
- **External services** (Last.fm/ListenBrainz) can run more frequently
- **Prevents LLM spam** with full 6h cooldown when the LLM succeeds
- **Allows recovery** with 1h cooldown when the LLM fails

---


## 📊 Monitoring and Metrics (Optional)

### METRICS_ENABLED
**Description**: Enable Prometheus metrics collection and HTTP server  
**Default**: `true`  
**Options**: `true`, `false`  
**Example**:
```bash
METRICS_ENABLED=true
```
**Notes**:
- Exposes metrics on port 9090 (configurable via METRICS_PORT)
- Provides counters, histograms, and gauges for monitoring
- Metrics include: playlists created, songs downloaded, API calls, latency, tokens used
- Access metrics at `http://localhost:9090/metrics`

---

### METRICS_PORT
**Description**: Port for Prometheus metrics HTTP server  
**Default**: `9090`  
**Range**: 1024-65535  
**Example**:
```bash
METRICS_PORT=9090
```
**Notes**:
- Only applies when METRICS_ENABLED=true
- Ensure port is not in use by another service
- Must be exposed in Docker: `-p 9090:9090`

---

### CIRCUIT_BREAKER_THRESHOLD
**Description**: Number of failures before opening circuit breaker  
**Default**: `5`  
**Range**: 1+  
**Example**:
```bash
CIRCUIT_BREAKER_THRESHOLD=5
```
**Notes**:
- Circuit breaker prevents cascading failures to external APIs
- After threshold failures, circuit opens and requests fail fast
- Helps protect external services from overload

---

### CIRCUIT_BREAKER_TIMEOUT
**Description**: Seconds to wait before attempting recovery  
**Default**: `60`  
**Range**: 10+  
**Example**:
```bash
CIRCUIT_BREAKER_TIMEOUT=60
```
**Notes**:
- After timeout, circuit enters half-open state and tries one request
- If successful, circuit closes; if failed, reopens for another timeout period

---

## 🌐 Web UI Dashboard (Optional)

### WEB_ENABLED
**Description**: Enable Flask web UI dashboard  
**Default**: `true`  
**Options**: `true`, `false`, `no`, `off`, `disabled`  
**Example**:
```bash
WEB_ENABLED=true
```
**Notes**:
- Provides real-time web-based monitoring dashboard
- Shows service health status with color-coded indicators
- Displays system statistics (playlists, cache, ratings)
- Auto-refreshes every 30 seconds
- Includes Swagger API documentation at `/apidocs/`
- Access at `http://localhost:5000` (or configured port)

---

### WEB_PORT
**Description**: Port for web UI HTTP server  
**Default**: `5000`  
**Range**: 1024-65535  
**Example**:
```bash
WEB_PORT=5000
```
**Notes**:
- Only applies when WEB_ENABLED=true
- Must be exposed in Docker: `-p 5000:5000`
- Dashboard includes:
  - System status and run times
  - Statistics (playlists created, songs rated, cache size)
  - Core services (Navidrome, Octo-Fiesta, LLM Engine)
  - Optional services (AudioMuse, Last.fm, ListenBrainz)
- API endpoints: `/api/health`, `/api/services`, `/api/stats`, `/api/status`

---

## 🕐 Time-of-Day Playlists (Optional)

### TIMEOFDAY_ENABLED
**Description**: Enable automatic time-period playlist generation  
**Default**: `true`  
**Options**: `true`, `false`  
**Example**:
```bash
TIMEOFDAY_ENABLED=true
```
**Notes**:
- Creates mood-appropriate playlists based on time of day
- Generates one playlist per time period (Morning/Afternoon/Evening/Night)
- Uses hybrid generation: 25 songs from AudioMuse + 5 from LLM
- **Time-gated**: Each playlist only generates at its designated hour (±30 minutes)
- **Morning Mix**: Generates at 4:00 AM only
- **Afternoon Flow**: Generates at 10:00 AM (noon) only
- **Evening Chill**: Generates at 4:00 PM only
- **Night Vibes**: Generates at 10:00 PM only
- Duplicate prevention: Won't regenerate within 1 hour
- Respects TZ environment variable for timezone
- Auto-deletes previous period's playlist when generating new one

---

### TIMEOFDAY_MORNING_START
**Description**: Hour when morning period starts (24-hour format)  
**Default**: `4`  
**Range**: 0-23  
**Example**:
```bash
TIMEOFDAY_MORNING_START=4
```

### TIMEOFDAY_MORNING_END
**Description**: Hour when morning period ends  
**Default**: `10`  

### TIMEOFDAY_AFTERNOON_START
**Description**: Hour when afternoon period starts  
**Default**: `10`  

### TIMEOFDAY_AFTERNOON_END
**Description**: Hour when afternoon period ends  
**Default**: `16`  

### TIMEOFDAY_EVENING_START
**Description**: Hour when evening period starts  
**Default**: `16`  

### TIMEOFDAY_EVENING_END
**Description**: Hour when evening period ends  
**Default**: `22`  

### TIMEOFDAY_NIGHT_START
**Description**: Hour when night period starts  
**Default**: `22`  

### TIMEOFDAY_NIGHT_END
**Description**: Hour when night period ends  
**Default**: `4`  

**Time Period Moods**:
- **Morning (4-10)**: Upbeat, energetic, positive vibes
- **Afternoon (10-16)**: Balanced, productive, moderate energy
- **Evening (16-22)**: Chill, relaxing, wind-down music
- **Night (22-4)**: Ambient, calm, sleep-friendly

---

### TIMEOFDAY_PLAYLIST_SIZE
**Description**: Number of songs in each time-period playlist  
**Default**: `30`  
**Range**: 10-100  
**Example**:
```bash
TIMEOFDAY_PLAYLIST_SIZE=30
```
**Notes**:
- Default: 25 from AudioMuse + 5 from LLM
- AudioMuse uses sonic analysis for similarity
- LLM adds variety and discovery
- Requires AudioMuse to be enabled for full 30 songs

---


- Period playlists now use time-gated generation
- Each period playlist only generates at its designated time (4am, 10am, 4pm, 10pm)
- Generation occurs within ±30 minute window of target time
- Duplicate prevention prevents multiple generations within 1 hour
- Tracked in `octogen_timeofday_last.json`
- Old period playlists are automatically deleted when new one generates

---

## ⚡ Batch Processing (Optional)

### DOWNLOAD_BATCH_SIZE
**Description**: Number of songs to download per batch  
**Default**: `5`  
**Range**: 1-50  
**Example**:
```bash
DOWNLOAD_BATCH_SIZE=10
```
**Notes**:
- Larger batches may be faster but use more memory
- Smaller batches provide better progress visibility
- Recommended: 5-10 for most use cases

---

### DOWNLOAD_CONCURRENCY
**Description**: Maximum concurrent downloads  
**Default**: `3`  
**Range**: 1-20  
**Example**:
```bash
DOWNLOAD_CONCURRENCY=5
```
**Notes**:
- Higher concurrency speeds up downloads but increases load
- Too high may cause timeouts or rate limiting
- Recommended: 3-5 for most use cases

---

## 📝 Logging Configuration (Optional)

### LOG_FORMAT
**Description**: Log output format  
**Default**: `text`  
**Options**: `text`, `json`  
**Example**:
```bash
LOG_FORMAT=json
```
**Notes**:
- `text`: Human-readable format (default)
- `json`: Structured JSON for log aggregation systems
- JSON format includes: timestamp, level, logger, message, context

---

### SHOW_PROGRESS
**Description**: Show progress indicators in terminal  
**Default**: `true`  
**Options**: `true`, `false`  
**Example**:
```bash
SHOW_PROGRESS=false
```
**Notes**:
- Displays progress bars and spinners for long operations
- Automatically disabled in non-TTY environments (Docker logs)
- Set to `false` if progress indicators cause issues

---

## 📋 Playlist Templates (Optional)

### PLAYLIST_TEMPLATES_FILE
**Description**: Path to playlist templates YAML file  
**Default**: `/config/playlist_templates.yaml`  
**Example**:
```bash
PLAYLIST_TEMPLATES_FILE=/custom/templates.yaml
```
**Notes**:
- Allows customization of playlist generation
- Default templates included: Morning Motivation, Focus Deep Work, Evening Wind Down, Workout Intensity
- Create custom templates with mood filters, genres, and characteristics
- Mount config directory: `-v ./config:/config`

---


## 🟢 Last.fm Integration (Optional)

### LASTFM_ENABLED
**Description**: Enable Last.fm recommendations  
**Default**: `false`  
**Options**: `true`, `false`  
**Example**:
```bash
LASTFM_ENABLED=true
```

---

### LASTFM_API_KEY
**Description**: Last.fm API key  
**Format**: String  
**Example**:
```bash
LASTFM_API_KEY=abc123xyz456...
```
**Get Key**: https://www.last.fm/api/account/create

---

### LASTFM_USERNAME
**Description**: Your Last.fm username  
**Format**: String  
**Example**:
```bash
LASTFM_USERNAME=your_username
```

---

## 🟢 ListenBrainz Integration (Optional)

### LISTENBRAINZ_ENABLED
**Description**: Enable ListenBrainz recommendations  
**Default**: `false`  
**Options**: `true`, `false`  
**Example**:
```bash
LISTENBRAINZ_ENABLED=true
```

---

### LISTENBRAINZ_USERNAME
**Description**: Your ListenBrainz username  
**Format**: String  
**Example**:
```bash
LISTENBRAINZ_USERNAME=your_username
```

---

### LISTENBRAINZ_TOKEN
**Description**: ListenBrainz user token  
**Format**: String  
**Example**:
```bash
LISTENBRAINZ_TOKEN=abc123-xyz456-...
```
**Get Token**: https://listenbrainz.org/profile/ → User token

---

## ⚙️ Performance Tuning (Optional)

### PERF_ALBUM_BATCH_SIZE
**Description**: Number of albums to fetch per API request  
**Default**: `500`  
**Range**: `100` to `1000`  
**Example**:
```bash
PERF_ALBUM_BATCH_SIZE=500
```
**Notes**:
- Higher = fewer API calls but more memory
- Lower = more API calls but less memory

---

### PERF_MAX_ALBUMS_SCAN
**Description**: Maximum albums to scan for ratings  
**Default**: `10000`  
**Range**: `1000` to `50000`  
**Example**:
```bash
PERF_MAX_ALBUMS_SCAN=10000
```
**Notes**:
- Prevents timeouts on huge libraries
- Increase if you have large library

---

### PERF_SCAN_TIMEOUT
**Description**: Timeout for Navidrome library scan (seconds)  
**Default**: `60`  
**Range**: `30` to `300`  
**Example**:
```bash
PERF_SCAN_TIMEOUT=60
```

---

### PERF_DOWNLOAD_DELAY
**Description**: Delay between downloads (seconds)  
**Default**: `10`  
**Range**: `1` to `30`  
**Example**:
```bash
PERF_DOWNLOAD_DELAY=6
```
**Notes**:
- Prevents overwhelming Octo-Fiesta
- Decrease for faster processing
- Increase if downloads fail

---

### PERF_POST_SCAN_DELAY
**Description**: Delay after Navidrome scan completes (seconds)  
**Default**: `10`  
**Range**: `1` to `10`  
**Example**:
```bash
PERF_POST_SCAN_DELAY=5
```
**Notes**:
- Ensures scan is fully complete before searching
- Increase if newly downloaded songs not found

---

## 🔧 System Configuration (Optional)

### LOG_LEVEL
**Description**: Logging verbosity level  
**Default**: `INFO`  
**Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`  
**Example**:
```bash
LOG_LEVEL=INFO
```
**When to use**:
- `DEBUG`: Troubleshooting, see all details
- `INFO`: Normal operation (recommended)
- `WARNING`: Only warnings and errors
- `ERROR`: Only errors

---

### OCTOGEN_DATA_DIR
**Description**: Directory for data storage (inside container)  
**Default**: `/data`  
**Example**:
```bash
OCTOGEN_DATA_DIR=/data
```
**Notes**:
- Usually don't need to change this
- Mount external volume to this path

---

## 📝 Complete Examples

### Minimal Configuration (Gemini)
```bash
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=secret123
OCTOFIESTA_URL=http://192.168.1.100:8080
AI_API_KEY=AIzaSyABC123...
```

### Scheduled Daily 
```bash
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=secret123
OCTOFIESTA_URL=http://192.168.1.100:8080
AI_API_KEY=AIzaSyABC123...

# Run daily at 6 AM local time
SCHEDULE_CRON=0 6 * * *
TZ=America/Chicago
```

### With Groq (Fast & Free)
```bash
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=secret123
OCTOFIESTA_URL=http://192.168.1.100:8080

AI_BACKEND=openai
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=llama-3.3-70b-versatile
AI_API_KEY=gsk_abc123...

# Every 12 hours
SCHEDULE_CRON=0 */12 * * *
TZ=America/New_York
```

### With Ollama (Local)
```bash
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=secret123
OCTOFIESTA_URL=http://192.168.1.100:8080

AI_BACKEND=openai
AI_BASE_URL=http://host.docker.internal:11434/v1
AI_MODEL=llama3.2
AI_API_KEY=ollama

# Weekly on Sunday at 3 AM
SCHEDULE_CRON=0 3 * * 0
TZ=UTC
```

### Full Featured with Scheduling
```bash
# Navidrome
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=secret123

# Octo-Fiesta
OCTOFIESTA_URL=http://192.168.1.100:8080

# AI (Gemini)
AI_API_KEY=AIzaSyABC123...
AI_MODEL=gemini-2.5-flash
AI_BACKEND=gemini
AI_MAX_CONTEXT_SONGS=500
AI_MAX_OUTPUT_TOKENS=65535

# Scheduling
SCHEDULE_CRON=0 6 * * *
TZ=America/Chicago

# Last.fm
LASTFM_ENABLED=true
LASTFM_API_KEY=your_lastfm_key
LASTFM_USERNAME=your_username

# ListenBrainz
LISTENBRAINZ_ENABLED=true
LISTENBRAINZ_USERNAME=your_listenbrainz_username
LISTENBRAINZ_TOKEN=your_token

# Performance
PERF_ALBUM_BATCH_SIZE=500
PERF_MAX_ALBUMS_SCAN=10000
PERF_SCAN_TIMEOUT=60
PERF_DOWNLOAD_DELAY=6
PERF_POST_SCAN_DELAY=2

# System
LOG_LEVEL=INFO
```

---

## 🎨 AudioMuse-AI Integration (Optional)

AudioMuse-AI provides sonic analysis-based playlist generation using audio feature extraction and similarity matching.

### AUDIOMUSE_ENABLED
**Description**: Enable AudioMuse-AI integration for hybrid playlist generation  
**Type**: Boolean  
**Default**: `false`  
**Options**: `true`, `false`  
**Example**:
```bash
AUDIOMUSE_ENABLED=true
```
**Notes**:
- When enabled, 10 playlists use hybrid mode (25 AudioMuse + 5 LLM songs)
- Hybrid playlists: Daily Mix 1-6, Chill Vibes, Workout Energy, Focus Flow, Drive Time
- Discovery remains LLM-only (50 songs) for new discoveries
- When disabled, all playlists use LLM-only mode
- Requires AudioMuse-AI server to be running and accessible
- Falls back to LLM-only if AudioMuse-AI is unreachable

---

### AUDIOMUSE_URL
**Description**: URL of your AudioMuse-AI server  
**Format**: `http://hostname:port` or `https://hostname:port`  
**Default**: `http://localhost:8000`  
**Examples**:
```bash
AUDIOMUSE_URL=http://localhost:8000
AUDIOMUSE_URL=http://audiomuse:8000
AUDIOMUSE_URL=http://192.168.1.100:8000
```
**Notes**:
- Do not include trailing slash
- If in Docker, can use service name: `http://audiomuse:8000`
- Health check is performed at startup

---

### AUDIOMUSE_AI_PROVIDER
**Description**: LLM provider for AudioMuse-AI playlist generation  
**Type**: String  
**Default**: `gemini`  
**Options**: `gemini`, `openai`, `ollama`, `mistral`  
**Example**:
```bash
AUDIOMUSE_AI_PROVIDER=gemini
```
**Notes**:
- Must match a provider supported by AudioMuse-AI
- Case-insensitive (converted to uppercase internally)

---

### AUDIOMUSE_AI_MODEL
**Description**: AI model to use with AudioMuse-AI  
**Type**: String  
**Default**: `gemini-2.5-flash`  
**Examples**:
```bash
AUDIOMUSE_AI_MODEL=gemini-2.5-flash
AUDIOMUSE_AI_MODEL=gpt-4o
AUDIOMUSE_AI_MODEL=llama3.2
```
**Notes**:
- Model must be supported by the selected LLM provider
- Gemini 2.5 Flash recommended for best cost/performance

---

### AUDIOMUSE_AI_API_KEY
**Description**: API key for the AudioMuse AI provider  
**Type**: String  
**Default**: Empty (not required for Ollama)  
**Example**:
```bash
AUDIOMUSE_AI_API_KEY=your_gemini_api_key_here
```
**Notes**:
- Required for: Gemini, OpenAI, Mistral
- Not required for: Ollama (local models)
- Keep this secret secure

---

### AUDIOMUSE_API_TOKEN
**Description**: Bearer token for authenticating to AudioMuse-AI itself  
**Type**: String  
**Default**: Empty  
**Example**:
```bash
AUDIOMUSE_API_TOKEN=4e1ad730643f5e1043...
```
**Notes**:
- Required when AudioMuse-AI runs with `AUTH_ENABLED=true` and an `API_TOKEN` configured
- Sent as `Authorization: Bearer <token>` on every request to AudioMuse-AI
  (`/api/config` health check and `/chat/api/chatPlaylist` playlist generation)
- Leave empty when AudioMuse-AI has authentication disabled
- This is *separate* from `AUDIOMUSE_AI_API_KEY` (which is the
  Gemini/OpenAI/Mistral key passed in the request body so AudioMuse can call
  the LLM on OctoGen’s behalf)
- Also supports Docker secrets via `AUDIOMUSE_API_TOKEN_FILE`

---

### AUDIOMUSE_SONGS_PER_MIX
**Description**: Number of songs from AudioMuse-AI per hybrid playlist  
**Type**: Integer  
**Default**: `25`  
**Range**: 1-30  
**Example**:
```bash
AUDIOMUSE_SONGS_PER_MIX=25
```
**Notes**:
- Total songs per hybrid playlist is always 30
- Remainder filled by LLM (see `LLM_SONGS_PER_MIX`)
- Applies to: Daily Mix 1-6, Chill Vibes, Workout Energy, Focus Flow, Drive Time
- Discovery always uses 50 LLM-only songs
- Example: 25 AudioMuse + 5 LLM = 30 total

---

### LLM_SONGS_PER_MIX
**Description**: Number of songs from LLM per hybrid playlist  
**Type**: Integer  
**Default**: `5`  
**Range**: 0-30  
**Example**:
```bash
LLM_SONGS_PER_MIX=5
```
**Notes**:
- Only applies when `AUDIOMUSE_ENABLED=true`
- When AudioMuse disabled, LLM provides all 30 songs
- Applies to: Daily Mix 1-6, Chill Vibes, Workout Energy, Focus Flow, Drive Time
- Discovery always uses 50 LLM-only songs regardless
- Ensure `AUDIOMUSE_SONGS_PER_MIX + LLM_SONGS_PER_MIX ≤ 30`

---

### AudioMuse-AI Setup Example

To enable hybrid mode with AudioMuse-AI:

```bash
# Enable AudioMuse integration
AUDIOMUSE_ENABLED=true
AUDIOMUSE_URL=http://audiomuse:8000

# Configure AI provider (same as main OctoGen)
AUDIOMUSE_AI_PROVIDER=gemini
AUDIOMUSE_AI_MODEL=gemini-2.5-flash
AUDIOMUSE_AI_API_KEY=your_api_key_here

# Adjust mix ratios (optional)
AUDIOMUSE_SONGS_PER_MIX=25
LLM_SONGS_PER_MIX=5
```

**Benefits of Hybrid Mode**:
- **AudioMuse-AI**: Sonic similarity, mood analysis, audio features
- **LLM**: Creative variety, metadata-based recommendations
- **Combined**: Best of both approaches for diverse, high-quality playlists
- **10 hybrid playlists**: Daily Mix 1-6, Chill Vibes, Workout Energy, Focus Flow, Drive Time
- **Discovery**: Remains LLM-only (50 songs) for fresh discoveries

---

## 🎵 Spotify Playlist Import (Optional)

Import public Spotify playlists directly into Navidrome. Requires a free Spotify Developer app (client credentials flow — no user login needed).

### SPOTIFY_IMPORT_ENABLED
**Description**: Enable Spotify playlist import  
**Default**: `false`  
**Example**:
```bash
SPOTIFY_IMPORT_ENABLED=true
```

---

### SPOTIFY_CLIENT_ID
**Description**: Spotify application client ID  
**Required**: If `SPOTIFY_IMPORT_ENABLED=true`  
**Example**:
```bash
SPOTIFY_CLIENT_ID=abc123def456...
```
**Get Key**: https://developer.spotify.com/dashboard (create a free app)
**Notes**:
- Supports Docker secrets

---

### SPOTIFY_CLIENT_SECRET
**Description**: Spotify application client secret  
**Required**: If `SPOTIFY_IMPORT_ENABLED=true`  
**Example**:
```bash
SPOTIFY_CLIENT_SECRET=xyz789...
```
**Notes**:
- Supports Docker secrets
- Keep this value secure

---

### SPOTIFY_PLAYLIST_URLS
**Description**: Comma-separated list of Spotify playlist URLs to import  
**Required**: If `SPOTIFY_IMPORT_ENABLED=true`  
**Example**:
```bash
SPOTIFY_PLAYLIST_URLS=https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M,https://open.spotify.com/playlist/37i9dQZEVXbNG2KDcFcKOF
```
**Notes**:
- Accepts full URLs (`https://open.spotify.com/playlist/<id>`) or bare playlist IDs
- Each playlist is created in Navidrome as `Spotify: <playlist_id>`
- Up to 100 tracks per playlist are imported

---

## 🎵 Deezer Playlist Import (Optional)

Import public Deezer playlists directly into Navidrome. No API credentials required.

### DEEZER_IMPORT_ENABLED
**Description**: Enable Deezer playlist import  
**Default**: `false`  
**Example**:
```bash
DEEZER_IMPORT_ENABLED=true
```

---

### DEEZER_PLAYLIST_URLS
**Description**: Comma-separated list of Deezer playlist URLs to import  
**Required**: If `DEEZER_IMPORT_ENABLED=true`  
**Example**:
```bash
DEEZER_PLAYLIST_URLS=https://www.deezer.com/playlist/1313621735,https://www.deezer.com/playlist/908622995
```
**Notes**:
- Accepts full URLs (`https://www.deezer.com/playlist/<id>`) or bare numeric IDs
- Each playlist is created in Navidrome as `Deezer: <playlist_id>`
- Up to 100 tracks per playlist are imported

---

## 🔗 Related Documentation

- **Main Documentation**: [README.md](README.md)
- **Cron Helper**: https://crontab.guru

---


## 🔐 Docker Secrets Support

OctoGen supports Docker secrets for secure management of sensitive configuration. All sensitive environment variables can be provided via Docker secrets.

### Supported Secrets

The following variables automatically check `/run/secrets/` first, then fall back to environment variables:

- `NAVIDROME_PASSWORD` → `/run/secrets/navidrome_password`
- `AI_API_KEY` → `/run/secrets/ai_api_key`
- `LASTFM_API_KEY` → `/run/secrets/lastfm_api_key`
- `LISTENBRAINZ_TOKEN` → `/run/secrets/listenbrainz_token`
- `AUDIOMUSE_AI_API_KEY` → `/run/secrets/audiomuse_ai_api_key`

### Docker Compose Example

```yaml
version: '3.8'

services:
  octogen:
    image: blueion76/octogen:latest
    secrets:
      - navidrome_password
      - ai_api_key
    environment:
      NAVIDROME_URL: "http://navidrome:4533"
      NAVIDROME_USER: "admin"
      # Password will be read from /run/secrets/navidrome_password
      OCTOFIESTA_URL: "http://octo-fiesta:8080"
      # AI key will be read from /run/secrets/ai_api_key

secrets:
  navidrome_password:
    file: ./secrets/navidrome_password.txt
  ai_api_key:
    file: ./secrets/ai_api_key.txt
```

### Creating Secrets

```bash
# Create secret files
mkdir -p secrets
echo "your_password" > secrets/navidrome_password.txt
echo "your_api_key" > secrets/ai_api_key.txt

# Or use Docker secrets in swarm mode
echo "your_password" | docker secret create navidrome_password -
```

### Priority

If the same variable is set multiple ways, OctoGen uses this priority:
1. Docker secret (`/run/secrets/`)
2. Environment variable
3. Default value (if applicable)

---
## 💡 Tips

### Docker Compose
Use `.env` file with docker-compose:
```yaml
services:
  octogen:
    image: blueion76/octogen:latest
    env_file:
      - .env
    restart: unless-stopped  # Important for scheduling!
```

### Docker Run
Pass environment file:
```bash
docker run -d \
  --env-file .env \
  --restart unless-stopped \
  blueion76/octogen:latest
```

### Docker Secrets
For production, use Docker secrets:
```bash
echo "your_password" | docker secret create navidrome_password -
```


### Troubleshooting Scheduling
```bash
# Check if scheduler is active
docker logs octogen | grep "SCHEDULER"

# See next run time
docker logs octogen | grep "Next scheduled run"

# Verify timezone
docker logs octogen | grep "Timezone:"

# Test cron expression
# Visit: https://crontab.guru
```

---

## Lidarr Bridge

Optional integration: when configured, OctoGen pushes the artist of any missing track to Lidarr after a configurable threshold of misses across runs. Failures never block playlist generation.

### LIDARR_URL
**Description**: Lidarr server URL. Setting this enables the bridge.
**Default**: unset (bridge disabled)
**Format**: `http://hostname:port`
**Example**:
```bash
LIDARR_URL=http://lidarr:8686
```

### LIDARR_API_KEY
**Description**: Lidarr API key (Settings → General).
**Required when**: `LIDARR_URL` is set.

### LIDARR_QUALITY_PROFILE
**Description**: Lidarr quality profile name (e.g. `Standard`). Resolved to ID at startup.
**Required when**: `LIDARR_URL` is set.

### LIDARR_METADATA_PROFILE
**Description**: Lidarr metadata profile name. Resolved to ID at startup.
**Required when**: `LIDARR_URL` is set.

### LIDARR_MIN_MISSING
**Description**: Number of missing-track encounters before pushing the artist to Lidarr.
**Default**: `3`
**Notes**: Counts persist across runs in OctoGen's SQLite cache.

### LIDARR_ADD_MONITORED
**Description**: Whether artists added by OctoGen are monitored in Lidarr.
**Default**: `false` (safer — opt in to downloads via the Lidarr UI)

### LIDARR_TAG
**Description**: Tag applied to every artist OctoGen adds to Lidarr.
**Default**: `octogen`
**Notes**:
- Created in Lidarr if it doesn't exist.
- Empty string disables tagging.
- Lets you filter / bulk-clean OctoGen-added artists later.

---

## 📊 Variable Summary

| Category | Count | Variables |
|----------|-------|-----------|
| **Required** | 4 | NAVIDROME_URL, NAVIDROME_USER, NAVIDROME_PASSWORD, OCTOFIESTA_URL |
| **AI Config** | 7 | AI_API_KEY (optional), AI_MODEL, AI_BACKEND, AI_BASE_URL, AI_MAX_CONTEXT_SONGS, AI_MAX_OUTPUT_TOKENS, AI_REQUEST_TIMEOUT |
| **Scheduling** | 2 | SCHEDULE_CRON, TZ, MIN_RUN_INTERVAL_HOURS |
| **Monitoring** | 4 | METRICS_ENABLED, METRICS_PORT, CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT |
| **Web UI** | 2 | WEB_ENABLED, WEB_PORT |
| **Time-of-Day** | 11 | TIMEOFDAY_ENABLED, TIMEOFDAY_*_START, TIMEOFDAY_*_END, TIMEOFDAY_PLAYLIST_SIZE, TIMEOFDAY_REFRESH_ON_PERIOD_CHANGE |
| **Batch Processing** | 2 | DOWNLOAD_BATCH_SIZE, DOWNLOAD_CONCURRENCY |
| **Logging** | 2 | LOG_FORMAT, SHOW_PROGRESS |
| **Templates** | 1 | PLAYLIST_TEMPLATES_FILE |
| **Last.fm** | 3 | LASTFM_ENABLED, LASTFM_API_KEY, LASTFM_USERNAME |
| **ListenBrainz** | 3 | LISTENBRAINZ_ENABLED, LISTENBRAINZ_USERNAME, LISTENBRAINZ_TOKEN |
| **AudioMuse-AI** | 8 | AUDIOMUSE_ENABLED, AUDIOMUSE_URL, AUDIOMUSE_AI_PROVIDER, AUDIOMUSE_AI_MODEL, AUDIOMUSE_AI_API_KEY, AUDIOMUSE_API_TOKEN, AUDIOMUSE_SONGS_PER_MIX, LLM_SONGS_PER_MIX |
| **Spotify Import** | 4 | SPOTIFY_IMPORT_ENABLED, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_PLAYLIST_URLS |
| **Deezer Import** | 2 | DEEZER_IMPORT_ENABLED, DEEZER_PLAYLIST_URLS |
| **Performance** | 5 | PERF_ALBUM_BATCH_SIZE, PERF_MAX_ALBUMS_SCAN, PERF_SCAN_TIMEOUT, PERF_DOWNLOAD_DELAY, PERF_POST_SCAN_DELAY |
| **System** | 2 | LOG_LEVEL, OCTOGEN_DATA_DIR |
| **Total** | **60** | |

**Note**: At least one music source must be configured: LLM, AudioMuse-AI, Last.fm, ListenBrainz, Spotify Import, or Deezer Import.

---

**All variables are documented with examples!** 📚

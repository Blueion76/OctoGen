# 🎵 OctoGen - Automatic Spotify-like Playlists for Navidrome

[![Docker Pulls](https://img.shields.io/docker/pulls/blueion76/octogen?logo=docker)](https://hub.docker.com/r/blueion76/octogen)

**OctoGen** automatically generates personalized music playlists for your Navidrome server using an LLM, LastFM, ListenBrainz and/or AudioMuse-AI seamlessly integrating with [Octo-Fiesta](https://github.com/V1ck3s/octo-fiesta) to download missing tracks.

Built with AI assistance. Contributions and pull requests welcome!

---

## ✨ Features

### 🤖 LLM-Powered Recommendations
- **Multiple LLM providers**: Gemini and OpenAI-compatible API-supported providers
- **Smart context caching**: Efficient, low-cost API usage
- **Variety seed**: Different recommendations every day

### 🎵 Generated Playlists
- **Discovery** (50 songs) - New music discoveries
- **Daily Mix 1-6** (30 songs each) - Genre-based mixes
- **Chill Vibes** (30 songs) - Relaxing tracks
- **Workout Energy** (30 songs) - High-energy music
- **Focus Flow** (30 songs) - Ambient/instrumental
- **Drive Time** (30 songs) - Upbeat driving music
- **Time-of-Day Playlist** (30 songs) - Mood-matched to current time period

**Total: 12 playlists, 380+ songs automatically curated!**

### 🕐 Time-of-Day Playlists

Automatic mood-appropriate playlists that rotate based on time of day:

- **Morning Mix (4 AM - 10 AM)**: Upbeat, energetic, positive vibes
- **Afternoon Flow (10 AM - 4 PM)**: Balanced, productive, moderate energy
- **Evening Chill (4 PM - 10 PM)**: Relaxing, wind-down music
- **Night Vibes (10 PM - 4 AM)**: Ambient, calm, sleep-friendly

**Features**:
- ✅ Hybrid generation: 25 songs from AudioMuse-AI + 5 from LLM
- ✅ Auto-rotates when time period changes
- ✅ Auto-deletes previous period's playlist
- ✅ Configurable time boundaries
- ✅ LLM prompts enhanced with time-of-day context

Enable with:
```bash
TIMEOFDAY_ENABLED=true
```

### 🎛️ Hybrid Mode (AudioMuse-AI Integration)

OctoGen can optionally integrate with **AudioMuse-AI** for enhanced sonic analysis:

- **Default Mode**: All playlists use LLM (current behavior)
- **Hybrid Mode**: Most playlists use 25 AudioMuse-AI + 5 LLM songs

Enable hybrid mode by setting:
```bash
AUDIOMUSE_ENABLED=true
AUDIOMUSE_URL=http://localhost:8000
```

**Hybrid playlists** (when AudioMuse enabled):
- **Daily Mix 1-6**: Genre-based mixes (25 AudioMuse + 5 LLM)
- **Chill Vibes**: Relaxing tracks (25 AudioMuse + 5 LLM)
- **Workout Energy**: High-energy music (25 AudioMuse + 5 LLM)
- **Focus Flow**: Ambient/instrumental (25 AudioMuse + 5 LLM)
- **Drive Time**: Upbeat driving music (25 AudioMuse + 5 LLM)
- **Time-of-Day Playlist**: Depends on time of day (25 AudioMuse + 5 LLM)

**LLM-only playlists** (always):
- **Discovery**: New discoveries (50 LLM songs)

This combines:
- **AudioMuse-AI**: Sonic similarity, mood analysis, audio feature matching
- **LLM**: Creative variety, metadata-based recommendations

See [AudioMuse-AI Setup](#-audiomuse-ai-setup-optional) below.

### 🎯 Smart Features
- **Star rating filtering**: Excludes 1-2 star rated songs
- **Duplicate detection**: No repeated tracks across playlists
- **Optional Octo-Fiesta integration** — auto-download missing tracks, or run local-only with `OCTOFIESTA_ENABLED=false`
- **Daily cache**: Efficient library scanning
- **Async operations**: Fast, parallel processing
- **LastFM, ListenBrainz & AudioMuse-AI**: Optional integrations
- **Built-in scheduling**: No external cron needed 🕐

### 📊 Monitoring & Observability
- **Web UI dashboard**: Real-time service health monitoring with auto-refresh
- **Prometheus metrics**: Track playlists, downloads, API calls, latency
- **Circuit breaker**: Prevents cascading failures to external APIs
- **Structured logging**: JSON format support for log aggregation
- **Health checks**: Monitor Navidrome, Octo-Fiesta, LLM, AudioMuse, LastFM, ListenBrainz

### ⚙️ Advanced Features
- **Modular architecture**: Clean, maintainable codebase
- **Batch processing**: Configurable concurrency for downloads
- **Docker secrets**: Secure credential management
- **Playlist templates**: Customizable via YAML configuration
- **Configuration validation**: Pydantic-based validation with helpful errors
- **Progress indicators**: Visual feedback for long operations

---

## 🚀 Quick Start

### Prerequisites
- **Navidrome** server running
- **Octo-Fiesta** configured for downloads
- **At least one music source**:
  - LLM API key (Gemini recommended - free tier available), OR
  - AudioMuse-AI configured, OR
  - LastFM enabled, OR
  - ListenBrainz enabled

### 1. Get API Key (Optional - if using LLM)
Visit: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### 2. Create Configuration

```bash
# Create .env file
cat > .env << 'EOF'
# Required
NAVIDROME_URL=http://192.168.1.100:4533
NAVIDROME_USER=admin
NAVIDROME_PASSWORD=your_password
OCTOFIESTA_URL=http://192.168.1.100:5274
AI_API_KEY=your_llm_api_key

# Optional
AI_MODEL=gemini-2.5-flash
AI_BACKEND=gemini
LOG_LEVEL=INFO

# Scheduling 
SCHEDULE_CRON=0 2 * * *
TZ=America/Chicago
EOF
```

### 3. Run with Docker

```bash
# Pull the image
docker pull blueion76/octogen:latest

# Run OctoGen with automatic scheduling
docker run -d \
  --name octogen \
  -v octogen-data:/data \
  --env-file .env \
  --restart unless-stopped \
  blueion76/octogen:latest

# Check logs (see countdown to next run!)
docker logs -f octogen
```

### 4. Check Your Navidrome
Open Navidrome and find your new playlists! 🎉

**Playlists update automatically at the time(s) you set your cronjob**

---


### Using Development Builds

To test the latest development version:
```bash
docker pull blueion76/octogen:dev
```

### Using Stable Releases

For production use (recommended):
```bash
docker pull blueion76/octogen:latest
```

## 🐳 Docker Compose (Recommended)

```yaml
version: '3.8'

services:
  octogen:
    image: blueion76/octogen:latest
    container_name: octogen
    restart: unless-stopped
    volumes:
      - octogen-data:/data
    environment:
      # Required
      NAVIDROME_URL: http://navidrome:4533
      NAVIDROME_USER: admin
      NAVIDROME_PASSWORD: ${NAVIDROME_PASSWORD}
      OCTOFIESTA_URL: http://octofiesta:5274
      AI_API_KEY: ${GEMINI_API_KEY}

      # Scheduling 
      SCHEDULE_CRON: "0 2,4,10,16,22 * * *"  # Daily at 2 AM, 4 AM, 10 AM, 4 PM and 10 PM
      TZ: America/Chicago

      # Optional
      AI_MODEL: gemini-2.5-flash
      AI_BACKEND: gemini
      LOG_LEVEL: INFO

volumes:
  octogen-data:
```

Run:
```bash
docker-compose up -d
docker-compose logs -f octogen
```

---

## 🌐 Web UI Dashboard

OctoGen includes a real-time monitoring dashboard accessible at `http://localhost:5000`.

### Features

- **Service Health Monitoring**: Real-time status for all connected services
  - Navidrome (connection, library stats)
  - Octo-Fiesta (connection status)
  - LLM Engine (backend, model, status)
  - AudioMuse-AI (enabled/disabled, health)
  - LastFM (enabled/disabled, connection)
  - ListenBrainz (enabled/disabled, connection)

- **System Statistics**:
  - Playlists created
  - Songs rated
  - Low-rated song count
  - Cache size
  - Last run timestamp
  - Next scheduled run

- **REST API**:
  - `GET /api/health` - Overall health status
  - `GET /api/services` - Detailed service information
  - `GET /api/stats` - System statistics
  - `GET /api/status` - Current run status

- **Auto-refresh**: Dashboard updates every 30 seconds

### Configuration

```bash
# Enable web UI (enabled by default)
WEB_ENABLED=true

# Configure port
WEB_PORT=5000
```

### Docker Setup

Expose port 5000 in your docker-compose.yml:

```yaml
services:
  octogen:
    image: blueion76/octogen:latest
    ports:
      - "5000:5000"  # Web UI dashboard
    environment:
      WEB_ENABLED: "true"
      WEB_PORT: "5000"
```

Access the dashboard at `http://localhost:5000` after starting the container.

---

## 🎨 AudioMuse-AI Setup (Optional)

To enable hybrid playlist generation with sonic analysis:

### 1. Install AudioMuse-AI

Follow the [AudioMuse-AI documentation](https://github.com/NeptuneHub/AudioMuse-AI) to deploy:


### 2. Run Initial Analysis

1. Open AudioMuse-AI at `http://localhost:8000`
2. Navigate to "Analysis and Clustering"
3. Click "Start Analysis" (one-time, analyzes your library)
4. Wait for completion

### 3. Enable in OctoGen

Add to your `.env`:

```bash
AUDIOMUSE_ENABLED=true
AUDIOMUSE_URL=http://localhost:8000
AUDIOMUSE_AI_PROVIDER=gemini
AUDIOMUSE_AI_MODEL=gemini-2.5-flash
AUDIOMUSE_AI_API_KEY=your_api_key_here
```

### 4. Adjust Mix Ratios (Optional)

```bash
AUDIOMUSE_SONGS_PER_MIX=25  # Songs from AudioMuse (default: 25)
LLM_SONGS_PER_MIX=5         # Songs from LLM (default: 5)
```

---

## 🔧 Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `NAVIDROME_URL` | Navidrome server URL | `http://192.168.1.100:4533` |
| `NAVIDROME_USER` | Navidrome username | `admin` |
| `NAVIDROME_PASSWORD` | Navidrome password | `your_password` |
| `OCTOFIESTA_URL` | Octo-Fiesta server URL | `http://192.168.1.100:5274` |

**Note**: At least one music source must also be configured:
- `AI_API_KEY` (for LLM-based playlists), OR
- `AUDIOMUSE_ENABLED=true` (for AudioMuse-AI sonic analysis), OR  
- `LASTFM_ENABLED=true` (for LastFM recommendations), OR
- `LISTENBRAINZ_ENABLED=true` (for ListenBrainz recommendations)

### Optional Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_MODEL` | `gemini-2.5-flash` | AI model to use |
| `AI_BACKEND` | `gemini` | Backend: `gemini` or `openai` |
| `AI_BASE_URL` | (none) | Custom API endpoint |
| `AI_REQUEST_TIMEOUT` | `300` | API request timeout in seconds |
| `SCHEDULE_CRON` | (none) | Cron schedule (e.g., `0 2 * * *`) |
| `TZ` | `UTC` | Timezone (e.g., `America/Chicago`) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

**See [ENV_VARS.md](ENV_VARS.md) for complete reference.**

---

## 🎯 LLM Provider Examples

### Gemini (Recommended - Free Tier)
```bash
AI_BACKEND=gemini
AI_MODEL=gemini-2.5-flash
AI_API_KEY=your_llm_api_key
```
**Get key:** [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)

### Groq (Fast & Free Tier)
```bash
AI_BACKEND=openai
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=llama-3.3-70b-versatile
AI_API_KEY=your_groq_api_key
```
**Get key:** [https://console.groq.com](https://console.groq.com)

### OpenAI (Official)
```bash
AI_BACKEND=openai
AI_MODEL=gpt-4o
AI_API_KEY=your_openai_api_key
```

### Ollama (Local, Offline)
```bash
AI_BACKEND=openai
AI_BASE_URL=http://host.docker.internal:11434/v1
AI_MODEL=llama3.2
AI_API_KEY=ollama
```

### OpenRouter (100+ Models)
```bash
AI_BACKEND=openai
AI_BASE_URL=https://openrouter.ai/api/v1
AI_MODEL=anthropic/claude-3.5-sonnet
AI_API_KEY=your_openrouter_api_key
```

---

## 🕐 Automatic Scheduling 

OctoGen includes **built-in cron scheduling** 

### Quick Setup

Just add these two environment variables:

```bash
SCHEDULE_CRON=0 2 * * *    # Daily at 2 AM
TZ=America/Chicago         # Your timezone
```

The container stays running and automatically executes on schedule. You'll see countdown logs:

```
🕐 OCTOGEN SCHEDULER
══════════════════════════════════════════════════════════════════════
Schedule: 0 2 * * *
Timezone: America/Chicago
══════════════════════════════════════════════════════════════════════
📅 Next scheduled run: 2026-02-11 06:00:00
⏰ Next run in 3.5 hours (2026-02-11 06:00:00)
```

### Schedule Examples

Music| Schedule | Cron Expression | Description |
|----------|----------------|-------------|
| Daily at 2 AM | `0 2 * * *` | Once per day |
| Twice daily | `0 */12 * * *` | Every 12 hours |
| Every 6 hours | `0 */6 * * *` | 4 times per day |
| Weekly (Sunday 3 AM) | `0 3 * * 0` | Once per week |
| Every Monday 9 AM | `0 9 * * 1` | Weekly on Monday |

**Cron Format:**
```
* * * * *
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

**Test your expressions:** [crontab.guru](https://crontab.guru)

### Timezone Configuration

**Important:** Set `TZ` to get correct local times! Without it, times are in UTC.

```bash
# United States
TZ=America/New_York        # Eastern
TZ=America/Chicago         # Central  
TZ=America/Denver          # Mountain
TZ=America/Los_Angeles     # Pacific

# Europe
TZ=Europe/London           # UK
TZ=Europe/Paris            # France
TZ=Europe/Berlin           # Germany

# Other
TZ=Asia/Tokyo              # Japan
TZ=Australia/Sydney        # Australia
```

### Manual Run (No Scheduling)

Leave `SCHEDULE_CRON` unset or set to `manual`:

---

## 📊 How It Works

### Architecture

OctoGen uses a modular architecture with clean separation of concerns:

```
octogen/
├── api/              # External API clients (Navidrome, LastFM, ListenBrainz, AudioMuse)
├── ai/               # Multi-backend LLM recommendation engine
├── monitoring/       # Prometheus metrics + circuit breaker
├── web/              # Flask dashboard
├── storage/          # SQLite ratings cache
├── models/           # Pydantic configuration validation
├── playlist/         # Template system
├── scheduler/        # Cron support
└── utils/            # Auth, secrets, retry, batch processing, logging
```

### Workflow

1. **Analyzes your Navidrome library**
   - Reads starred/favorited songs
   - Identifies top artists and genres
   - Caches ratings (daily refresh for performance)

2. **Generates LLM recommendations**
   - Sends music profile to LLM (or uses AudioMuse/LastFM/ListenBrainz)
   - Excludes low-rated songs (1-2 stars)
   - Requests 11 themed playlists with variety

3. **Smart processing**
   - Checks which songs exist in library (fuzzy matching)
   - Detects and prevents duplicates
   - Triggers downloads for missing tracks via Octo-Fiesta
   - Processes in batches with configurable concurrency

4. **Creates playlists in Navidrome**
   - Builds 11 themed playlists
   - Mixes library favorites with discoveries
   - Applies star rating filters

5. **Monitoring & scheduling**
   - Records metrics (if enabled)
   - Updates web dashboard (if enabled)
   - Waits for next scheduled run (if configured)
   - Automatically retries on errors with circuit breaker

### Components

- **Navidrome API**: Library reading, playlist creation, rating management
- **LLM Provider**: Personalized recommendations (Gemini, OpenAI, Groq, Ollama, etc.)
- **Octo-Fiesta**: Automatic download of missing tracks
- **SQLite Cache**: Rating storage with daily refresh
- **Circuit Breaker**: Prevents cascading failures to external APIs
- **Prometheus**: Metrics collection for monitoring (optional)
- **Web Dashboard**: Real-time monitoring interface (optional)
- **Scheduler**: Built-in cron for automatic execution

---

## 🧪 Dry Run Mode

Test without making changes:

```bash
docker run --rm \
  -v octogen-data:/data \
  --env-file .env \
  blueion76/octogen:latest \
  python octogen.py --dry-run
```

Shows what would happen without:
- Downloading songs
- Creating playlists
- Making any changes

---

## 📁 Data Persistence

OctoGen stores data in `/data`:

```
/data/
├── octogen.log              # Application logs
├── octogen_cache.db         # Star ratings cache
├── gemini_cache.json        # LLM context cache
└── octogen.lock             # Prevents duplicate runs
```

Mount a volume to persist data:
```bash
-v octogen-data:/data
```

---

## 🔍 Monitoring

### Logs

View container logs:
```bash
# Real-time logs
docker logs -f octogen

# Last 100 lines
docker logs --tail 100 octogen

# Save to file
docker logs octogen > octogen.log
```

Logs show:
- ✅ Successful operations (green checkmarks)
- ⚠️ Warnings (yellow)
- ❌ Errors (red)
- 🕐 Scheduled run countdown
- 📊 Statistics (playlists created, songs downloaded)

### Prometheus Metrics (Optional)

Enable metrics collection:
```bash
# In .env or docker-compose.yml
METRICS_ENABLED=true
METRICS_PORT=9090

# Expose port
docker run -p 9090:9090 ...
```

Access metrics:
```bash
# Metrics endpoint
curl http://localhost:9090/metrics
```

Available metrics:
- `octogen_playlists_created_total{source}` - Playlists created
- `octogen_songs_downloaded_total` - Songs downloaded
- `octogen_api_calls_total{service,status}` - API calls
- `octogen_api_latency_seconds{service}` - API latency
- `octogen_ai_tokens_used` - LLM tokens consumed
- `octogen_last_run_timestamp` - Last successful run
- `octogen_last_run_duration_seconds` - Run duration

Integrate with Prometheus:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'octogen'
    static_configs:
      - targets: ['octogen:9090']
```

### Web UI Dashboard (Optional)

Enable web dashboard for real-time monitoring:
```bash
# In .env or docker-compose.yml
WEB_UI_ENABLED=true
WEB_UI_PORT=5000

# Expose port
docker run -p 5000:5000 ...
```

Access dashboard at: `http://localhost:5000`

Dashboard shows:
- Real-time status and health
- Statistics (playlists, downloads, failures)
- Service health checks (Navidrome, Octo-Fiesta)
- Auto-refreshes every 30 seconds

### Check Status

```bash
# Container status
docker ps -a | grep octogen

# Resource usage
docker stats octogen

# Health check file
docker exec octogen cat /data/health.json

# Verify scheduler
docker logs octogen | grep "SCHEDULER"

# See next run time
docker logs octogen | grep "Next scheduled run"

# Verify timezone
docker logs octogen | grep "Timezone:"
```

### Verify Data

```bash
# Check data directory
docker exec octogen ls -lh /data

# View log file
docker exec octogen tail -n 50 /data/octogen.log

# Check cache
docker exec octogen sqlite3 /data/octogen_cache.db "SELECT COUNT(*) FROM ratings;"
```

---

## 🛠️ Troubleshooting

### Problem: "Can't connect to Navidrome"

**Solution:**
- Check `NAVIDROME_URL` is correct
- Use Docker network name if both containers on same network
- Try: `http://navidrome:4533` instead of `http://localhost:4533`

### Problem: "AI API error"

**Solution:**
- Verify API key is correct
- Check API provider status
- Ensure you have API credits/quota
- Try different model if rate limited

### Problem: "No playlists created"

**Solution:**
- Check logs: `docker logs octogen`
- Ensure you have starred songs in Navidrome
- Verify Octo-Fiesta is running
- Try dry-run mode to see what would happen

### Problem: "Downloads not working"

**Solution:**
- Verify `OCTOFIESTA_URL` is correct
- Check Octo-Fiesta is configured properly
- Ensure Navidrome credentials are correct
- Check network connectivity between containers

### Problem: "Scheduler not working"

**Solution:**
- Verify `SCHEDULE_CRON` is set: `docker inspect octogen | grep SCHEDULE_CRON`
- Check logs for "OCTOGEN SCHEDULER" message
- Ensure container has restart policy: `--restart unless-stopped`
- Verify timezone: `docker logs octogen | grep "Timezone:"`

### Problem: "Wrong time scheduled"

**Solution:**
- Set `TZ` environment variable to your timezone
- Without `TZ`, times are in UTC
- Check current timezone in logs
- Test cron expression at [crontab.guru](https://crontab.guru)

---


**Components:**
- **Navidrome API**: Reads library, creates playlists
- **LLM Provider**: Generates recommendations
- **Octo-Fiesta**: Downloads missing tracks
- **SQLite Cache**: Stores ratings (daily refresh)
- **Logs**: Application activity
- **Built-in Scheduler**: Automatic execution 

---

## 📚 Documentation

- **[ENV_VARS.md](ENV_VARS.md)** - Complete environment variables reference

---

## 🧪 Running Tests

Install runtime and development dependencies, then run the test suite with pytest:

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest tests/
```

---

## 🤝 Contributing

Contributions welcome! Just create a pull request.

---

## 🙏 Acknowledgments

- **[Navidrome](https://www.navidrome.org/)** - Open-source music server
- **[Octo-Fiesta](https://github.com/V1ck3s/octo-fiesta)** - Automated music downloader
- **[LastFM](https://www.last.fm/)** - Music discovery API
- **[ListenBrainz](https://listenbrainz.org/)** - Open music metadata
- **[AudioMuse-AI](https://github.com/NeptuneHub/AudioMuse-AI)** - In-depth analysis of your music library

---

## 🔗 Links

- **Docker Hub**: [hub.docker.com/r/blueion76/octogen](https://hub.docker.com/r/blueion76/octogen)
- **GitHub**: [github.com/Blueion76/Octogen](https://github.com/Blueion76/Octogen)
- **Issues**: [github.com/Blueion76/Octogen/issues](https://github.com/Blueion76/Octogen/issues)

---

## ⭐ Star History

If you find this project useful, please consider giving it a star! ⭐

---

**Made with ❤️ for the self-hosted music community**

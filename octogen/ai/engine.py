"""AI music recommendation engine with configurable backends"""

import hashlib
import json
from json_repair import repair_json
import logging
import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

from octogen.storage.cache import LOW_RATING_MIN, LOW_RATING_MAX

# Try to import OpenAI
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Try to import Gemini SDK
try:
    from google import genai
    from google.genai import types
    GEMINI_SDK_AVAILABLE = True
except ImportError:
    GEMINI_SDK_AVAILABLE = False


logger = logging.getLogger(__name__)


class AIRecommendationEngine:
    """AI music recommendations with configurable backend."""

    def __init__(
        self,
        api_key: str,
        model: str,
        backend: str = "gemini",
        base_url: Optional[str] = None,
        max_context_songs: int = 500,
        max_output_tokens: int = 65535,
        request_timeout: int = 300,
        data_dir: Optional[Path] = None,
    ):
        """Initialize AI recommendation engine.
        
        Args:
            api_key: API key for AI service
            model: Model name
            backend: Backend type (gemini, openai, etc.)
            base_url: Optional base URL for OpenAI-compatible APIs
            max_context_songs: Maximum songs to include in context
            max_output_tokens: Maximum output tokens
            request_timeout: Timeout in seconds for each API request
            data_dir: Data directory for cache files
        """
        self.api_key = api_key
        self.model = model
        self.backend = backend.lower()
        self.max_context_songs = max_context_songs
        self.max_output_tokens = max_output_tokens
        self.request_timeout = request_timeout
        
        # Set up data directory
        if data_dir is None:
            data_dir = Path(os.getenv("OCTOGEN_DATA_DIR", Path.cwd()))
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.cache_file = self.data_dir / "gemini_cache.json"
        self.call_tracker_file = self.data_dir / "ai_last_call.json"
        self.library_hash_file = self.data_dir / "library_hash.txt"
        
        # State management
        self.call_count = 0
        self.max_calls = 1
        self.response_cache: Optional[Dict[str, List[Dict]]] = None

        logger.info("✓ AI Backend: %s", self.backend)
        logger.info("✓ AI Model: %s", self.model)

        if self.backend == "gemini":
            if not GEMINI_SDK_AVAILABLE:
                logger.error("Gemini backend selected but google-genai not installed!")
                logger.error("Run: pip install google-genai")
                sys.exit(1)
            self.genai_client = genai.Client(api_key=api_key)
            logger.info("✓ Gemini SDK initialized with caching support")
        else:
            if OpenAI is None:
                logger.error("OpenAI library not installed!")
                logger.error("Run: pip install openai")
                sys.exit(1)
            if base_url:
                self.client = OpenAI(api_key=api_key, base_url=base_url)
                logger.info("✓ OpenAI-compatible API: %s", base_url)
            else:
                self.client = OpenAI(api_key=api_key)
                logger.info("✓ OpenAI API initialized")
    
    def get_time_context(self) -> Optional[Dict[str, str]]:
        """Get time-of-day context for AI prompts.
        
        Returns:
            Dict with time context or None if not enabled
        """
        try:
            from octogen.scheduler.timeofday import get_time_context as get_tod_context
            import os
            
            # Check if time-of-day feature is enabled
            enabled = os.getenv("TIMEOFDAY_ENABLED", "true").lower() in ("true", "yes", "1", "on")
            if not enabled:
                return None
            
            return get_tod_context()
        except Exception as e:
            logger.warning(f"Could not get time context: {e}")
            return None
    
    def analyze_listening_profile(self, favorited_songs: List[Dict], top_artists: List[str], top_genres: List[str]) -> Dict[str, Any]:
        """Analyze user's listening profile for better recommendations.
        
        Args:
            favorited_songs: List of favorited songs
            top_artists: Top artists
            top_genres: Top genres
            
        Returns:
            Dict with profile insights
        """
        profile = {
            "total_songs": len(favorited_songs),
            "top_artists": top_artists[:10],
            "top_genres": top_genres[:6],
            "diversity_score": 0.0,
            "artist_distribution": {}
        }
        
        # Calculate artist distribution
        from collections import Counter
        artist_counts = Counter(song.get("artist", "Unknown") for song in favorited_songs)
        total = len(favorited_songs)
        
        # Diversity score: higher when more evenly distributed
        if total > 0:
            # Calculate normalized Shannon entropy
            entropy = -sum((count/total) * math.log2(count/total) for count in artist_counts.values() if count > 0)
            max_entropy = math.log2(len(artist_counts)) if len(artist_counts) > 1 else 1
            profile["diversity_score"] = min(entropy / max_entropy, 1.0) if max_entropy > 0 else 0
        
        profile["artist_distribution"] = dict(artist_counts.most_common(10))
        
        return profile

    def _can_call_ai_today(self) -> bool:
        """Check if AI can be called today (once per day limit).
        
        Returns:
            True if AI can be called today
        """
        if not self.call_tracker_file.exists():
            return True
        
        try:
            with open(self.call_tracker_file, 'r') as f:
                data = json.load(f)
                last_call_date = data.get('last_call_date')
                today = datetime.now().strftime("%Y-%m-%d")
                
                if last_call_date == today:
                    logger.warning("AI already called today (%s). Using cached data or skipping.", today)
                    return False
                return True
        except Exception as e:
            logger.warning("Could not read call tracker: %s", str(e))
            return True
    
    def _record_ai_call(self) -> None:
        """Record that AI was called today."""
        try:
            with open(self.call_tracker_file, 'w') as f:
                json.dump({
                    'last_call_date': datetime.now().strftime("%Y-%m-%d"),
                    'last_call_timestamp': datetime.now().isoformat()
                }, f)
            logger.info("Recorded AI call timestamp")
        except Exception as e:
            logger.error("Could not write call tracker: %s", str(e))
            
    def _get_library_hash(self, favorited_songs: List[Dict]) -> str:
        """Generate hash of library for cache invalidation.
        
        Args:
            favorited_songs: List of favorited songs
            
        Returns:
            MD5 hash string
        """
        # Hash based on song count and sample of song IDs
        # Using first 20 and last 20 songs to detect changes
        sample_size = min(20, len(favorited_songs))
        first_songs = [s.get("id", "") for s in favorited_songs[:sample_size]]
        last_songs = [s.get("id", "") for s in favorited_songs[-sample_size:]]
        
        hash_input = f"{len(favorited_songs)}:{','.join(first_songs)}:{','.join(last_songs)}"
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _should_invalidate_cache(self, favorited_songs: List[Dict]) -> bool:
        """Check if library changed significantly since last cache.
        
        Args:
            favorited_songs: List of favorited songs
            
        Returns:
            True if cache should be invalidated
        """
        current_hash = self._get_library_hash(favorited_songs)
        
        # If no previous hash, store current and don't invalidate
        if not self.library_hash_file.exists():
            logger.info("First run - storing library fingerprint")
            try:
                self.library_hash_file.write_text(current_hash)
            except Exception as e:
                logger.warning("Could not write library hash: %s", str(e))
            return False
        
        try:
            stored_hash = self.library_hash_file.read_text().strip()
        except Exception as e:
            logger.warning("Could not read library hash: %s", str(e))
            return False
        
        if current_hash != stored_hash:
            logger.info("Library changed detected (songs added/removed)")
            logger.info("  Previous library fingerprint: %s", stored_hash[:8])
            logger.info("  Current library fingerprint:  %s", current_hash[:8])
            
            # Update stored hash
            try:
                self.library_hash_file.write_text(current_hash)
            except Exception as e:
                logger.warning("Could not update library hash: %s", str(e))
            
            return True
        
        return False
    
    def _invalidate_cache(self) -> None:
        """Invalidate all caches (in-memory and on-disk)."""
        logger.info("Invalidating AI caches...")
        
        # Clear in-memory cache
        self.response_cache = None
        
        # Delete Gemini cache file
        if self.cache_file.exists():
            try:
                self.cache_file.unlink()
                logger.info("  Deleted Gemini cache file")
            except Exception as e:
                logger.warning("  Could not delete cache file: %s", str(e))
        
        # Note: We don't delete call tracker to preserve daily limit
        logger.info("Cache invalidation complete")

    def _load_recent_songs(self) -> set:
        """Load recently recommended songs from disk.
        
        Returns:
            Set of "artist - title" strings from recent runs, or empty set on failure.
        """
        recent_file = self.data_dir / "recent_playlist_songs.json"
        try:
            if recent_file.exists():
                with open(recent_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            logger.warning("Could not load recent songs: %s", str(e)[:100])
        return set()

    def _save_recent_songs(self, songs: list) -> None:
        """Save recently recommended songs to disk (capped at 200 entries across last 2 runs).

        The file is written atomically (temp file + os.replace) so an interrupted
        write never leaves a corrupt or empty file on disk.

        Args:
            songs: List of song dicts with "artist" and "title" keys from the new playlists.
        """
        recent_file = self.data_dir / "recent_playlist_songs.json"
        try:
            existing = self._load_recent_songs()
            new_entries = [
                f"{s.get('artist', '')} - {s.get('title', '')}"
                for s in songs
                if s.get('artist') and s.get('title')
            ]
            # Build ordered list: existing first (oldest), new entries appended last
            # so that truncation with [-200:] always keeps the most recent songs.
            seen: set = set()
            ordered: list = []
            for entry in list(existing) + new_entries:
                if entry not in seen:
                    seen.add(entry)
                    ordered.append(entry)
            # Cap at 200 entries (approximately 2 runs worth); drop oldest first
            combined = ordered[-200:]
            # Atomic write: write to a sibling temp file then replace
            tmp_file = recent_file.with_suffix(".json.tmp")
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(combined, f, ensure_ascii=False)
            os.replace(tmp_file, recent_file)
            logger.info("Saved %d recent songs to disk (%d total)", len(new_entries), len(combined))
        except Exception as e:
            logger.warning("Could not save recent songs: %s", str(e)[:100])

    def _build_cached_context(
        self,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
    ) -> str:
        """Build the static context that will be cached.
        
        Args:
            top_artists: List of top artist names
            top_genres: List of top genres
            favorited_songs: List of favorited songs
            low_rated_songs: Optional list of low-rated songs to avoid
            
        Returns:
            Context string for AI
        """
        artist_list = ", ".join(random.sample(top_artists[:20], min(10, len(top_artists[:20]))))
        genre_list = ", ".join(random.sample(top_genres[:12], min(6, len(top_genres[:12]))))

        # Randomly sample a subset for variety — avoids O(n) shuffle of the full library
        k = min(self.max_context_songs, len(favorited_songs))
        favorited_sample = [
            f"{s.get('artist','')} - {s.get('title','')}"
            for s in random.sample(favorited_songs, k)
        ]
        favorited_context = "\n".join(favorited_sample)

        negative_context = ""
        if low_rated_songs:
            negative_sample = [
                f"{s.get('artist','')} - {s.get('title','')}"
                for s in low_rated_songs[:50]
            ]
            negative_context = f"""
SONGS TO AVOID (rated {LOW_RATING_MIN}-{LOW_RATING_MAX} stars by user):
{chr(10).join(negative_sample)}
CRITICAL: Never recommend these songs or very similar style/sound."""

        return f"""You are a JSON API for music recommendations.

USER MUSIC PROFILE:
- Favorited songs: {len(favorited_songs)}
- Top artists: {artist_list}
- Top genres: {genre_list}

SAMPLE FAVORITED SONGS:
{favorited_context}{negative_context}

Use songs from this library for "library songs" and recommend NEW similar songs."""

    def _get_or_create_gemini_cache(
        self,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
    ):
        """Get or create Gemini cached content with daily invalidation.
        
        Args:
            top_artists: List of top artist names
            top_genres: List of top genres
            favorited_songs: List of favorited songs
            low_rated_songs: Optional list of low-rated songs
            
        Returns:
            Gemini cached content object
        """
        today = datetime.now().strftime("%Y-%m-%d")

        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache_data = json.load(f)
                cache_name = cache_data.get("name")
                cache_date = cache_data.get("date")

                # Invalidate if cache is from previous day
                if cache_date == today:
                    try:
                        cached_content = self.genai_client.caches.get(name=cache_name)
                        logger.info("Using existing cache: %s", cache_name)
                        return cached_content
                    except Exception:
                        pass
                else:
                    logger.info("Cache is from previous day, creating fresh cache")
            except Exception as e:
                logger.warning("Cache invalid: %s", str(e)[:100])
                if self.cache_file.exists():
                    self.cache_file.unlink()

        # Shuffle songs for daily variety
        shuffled_songs = favorited_songs.copy()
        random.shuffle(shuffled_songs)

        cached_content_text = self._build_cached_context(
            top_artists, top_genres, shuffled_songs, low_rated_songs
        )

        logger.info("Creating context cache (10-20 seconds)...")
        cached_content = self.genai_client.caches.create(
            model=self.model,
            config={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": cached_content_text}]
                    }
                ],
                "ttl": "86400s",  # 24 hours
            }
        )

        with open(self.cache_file, 'w') as f:
            json.dump({
                "name": cached_content.name,
                "created": datetime.now().isoformat(),
                "date": today
            }, f)

        logger.info("Cache created: %s (expires in 24 hours)", cached_content.name)
        return cached_content

    def _build_task_prompt(
        self,
        top_genres: List[str],
        time_context: Optional[Dict[str, str]] = None,
        recent_songs: Optional[set] = None,
    ) -> str:
        """Build the task-specific prompt with optional time-of-day awareness.
        
        Args:
            top_genres: List of top genres
            time_context: Optional time-of-day context from get_time_context()
            recent_songs: Optional set of recently recommended "artist - title" strings to avoid
            
        Returns:
            Task prompt string
        """
        top_genres_list = top_genres if top_genres else ["Mix"]
        genre_instructions = []

        for i in range(6):
            genre_name = top_genres_list[i] if i < len(top_genres_list) else "Mix"
            genre_instructions.append(
                f'{i+2}. "Daily Mix {i+1}" (30 songs, genre: {genre_name}): 25 library + 5 new'
            )

        variety_seed = random.randint(100000, 999999)  # 6-digit range reduces collision probability across runs

        # Pick a random decade bias hint for added variety
        decade_hints = ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s", "Mix of all eras"]
        decade_hint = random.choice(decade_hints)
        
        # Add time-of-day context if provided
        time_guidance = ""
        if time_context:
            time_guidance = f"""
TIME-OF-DAY CONTEXT:
Current period: {time_context.get('description', 'N/A')}
Recommended mood: {time_context.get('mood', 'balanced')}
Energy level: {time_context.get('energy', 'medium')}
Guidance: {time_context.get('guidance', '')}

Apply this context when selecting NEW songs to match the current time of day.
"""

        # Add recently recommended songs section if provided
        recent_songs_section = ""
        if recent_songs:
            sample_size = min(40, len(recent_songs))
            recent_sample = random.sample(sorted(recent_songs), sample_size)
            recent_songs_section = f"""
RECENTLY RECOMMENDED (avoid repeating these):
{chr(10).join(recent_sample)}
"""

        return f"""Generate exactly 11 playlists (Variety Seed: {variety_seed}):

1. "Discovery" (50 songs): 45 new discoveries + 5 library
{chr(10).join(genre_instructions)}
8. "Chill Vibes" (30 songs): 25 library + 5 new relaxing
9. "Workout Energy" (30 songs): 25 library + 5 new high-energy
10. "Focus Flow" (30 songs): 25 library + 5 new ambient/instrumental
11. "Drive Time" (30 songs): 25 library + 5 new upbeat
Decade focus: {decade_hint} — lean toward this era for new discoveries
{time_guidance}{recent_songs_section}
Respond ONLY with a valid JSON array of objects, each with "artist" and "title" fields, using double quotes.

{{
  "Discovery": [
    {{"artist": "Artist", "title": "Song"}},
    {{"artist": "Artist", "title": "Song"}}
  ],
  "Daily Mix 1": [{{"artist": "Artist", "title": "Song"}}]
}}

CRITICAL RULES:
- Both "artist" and "title" required
- Double quotes for ALL strings
- No trailing commas
- NEVER recommend avoided songs
- No markdown, just raw JSON
- ESCAPE ALL BACKSLASHES: Use \\\\ not \\
- If song title has backslash, use double backslash
- Example: "AC\\\\DC" not "AC\\DC"
- Maximize variety: no artist should appear more than 2 times per playlist
- Each playlist MUST have a different set of songs - NO song should appear in more than one playlist
- Prioritize LESS POPULAR and DEEPER CUTS over well-known hits
"""

    def _generate_with_gemini(
        self,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
    ) -> str:
        """Generate playlists using Gemini SDK with caching.
        
        Args:
            top_artists: List of top artist names
            top_genres: List of top genres
            favorited_songs: List of favorited songs
            low_rated_songs: Optional list of low-rated songs
            
        Returns:
            JSON response string
        """
        cached_content = self._get_or_create_gemini_cache(
            top_artists, top_genres, favorited_songs, low_rated_songs
        )

        # Get time-of-day context
        time_context = self.get_time_context()
        if time_context:
            logger.info(f"🕐 Time context: {time_context.get('description')} - {time_context.get('mood')}")
        
        recent_songs = self._load_recent_songs()
        prompt = self._build_task_prompt(top_genres, time_context, recent_songs)

        # Set thinking budget
        thinking_budget = 5000

        response = self.genai_client.models.generate_content(
            model=cached_content.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                cached_content=cached_content.name,
                temperature=0.8,
                max_output_tokens=self.max_output_tokens,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget)
            )
        )

        if hasattr(response, 'usage_metadata'):
            metadata = response.usage_metadata
            thoughts = getattr(metadata, 'thoughtsTokenCount', 0)
            output = getattr(metadata, 'candidates_token_count', 0)
            logger.info("Tokens - Cached: %d, Input: %d, Output: %d, Thoughts: %d",
                       getattr(metadata, 'cached_content_token_count', 0),
                       getattr(metadata, 'prompt_token_count', 0),
                       output,
                       thoughts)

            # Warn if thinking budget was too low
            if thoughts >= thinking_budget * 0.95:
                logger.warning("Thinking budget nearly exhausted (%d/%d tokens)",
                             thoughts, thinking_budget)

        # Check for empty response
        if not response.text or response.text.strip() == "":
            logger.error("Gemini returned empty response")
            raise ValueError("Empty response from Gemini")
        
        # Validate JSON structure
        try:
            json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            logger.debug(f"Problematic response start: {response.text[:500]}")
            raise ValueError("Invalid JSON response from Gemini") from e
            
        return response.text
        
    def _generate_with_openai(
        self,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
    ) -> str:
        """Generate playlists using OpenAI library.
        
        Args:
            top_artists: List of top artist names
            top_genres: List of top genres
            favorited_songs: List of favorited songs
            low_rated_songs: Optional list of low-rated songs
            
        Returns:
            JSON response string
        """
        cached_context = self._build_cached_context(
            top_artists, top_genres, favorited_songs, low_rated_songs
        )

        # Get time-of-day context
        time_context = self.get_time_context()
        if time_context:
            logger.info(f"🕐 Time context: {time_context.get('description')} - {time_context.get('mood')}")
        
        recent_songs = self._load_recent_songs()
        task_prompt = self._build_task_prompt(top_genres, time_context, recent_songs)
        full_prompt = f"{cached_context}\n\n{task_prompt}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.8,
            max_tokens=self.max_output_tokens,
            response_format={"type": "json_object"},
            timeout=self.request_timeout,
        )

        return response.choices[0].message.content.strip()
        
    def generate_all_playlists(
        self,
        top_artists: List[str],
        top_genres: List[str],
        favorited_songs: List[Dict],
        low_rated_songs: Optional[List[Dict]] = None,
    ) -> Tuple[Dict[str, List[Dict]], Optional[str]]:
        """Generate playlists using configured backend.
    
        Args:
            top_artists: List of top artist names
            top_genres: List of top genres
            favorited_songs: List of favorited songs
            low_rated_songs: Optional list of low-rated songs
    
        Returns:
            Tuple of (playlists_dict, error_reason)
            - playlists_dict: Dictionary of playlist names to song lists
            - error_reason: None if successful, or error code string like 'rate_limit', 'quota_exceeded', 'invalid_response', 'api_error'
        """
    
        # Check if library changed and invalidate cache if needed
        if self._should_invalidate_cache(favorited_songs):
            self._invalidate_cache()
    
        # Check memory cache first
        if self.response_cache is not None:
            logger.info("Using cached AI response (in-memory)")
            return self.response_cache, None
    
        # Check daily limit BEFORE checking call count
        if not self._can_call_ai_today():
            logger.error("Daily AI call limit reached. Program can restart but won't call AI again today.")
            return {}, "quota_exceeded"
    
        if self.call_count >= self.max_calls:
            logger.error("AI call limit reached (%d)", self.max_calls)
            return {}, "quota_exceeded"
    
        logger.info("Making LLM API call (%d/%d)...", self.call_count + 1, self.max_calls)
        self.call_count += 1
    
        try:
            if self.backend == "gemini":
                content = self._generate_with_retry(
                    self._generate_with_gemini,
                    top_artists, top_genres, favorited_songs, low_rated_songs
                )
            else:
                content = self._generate_with_retry(
                    self._generate_with_openai,
                    top_artists, top_genres, favorited_songs, low_rated_songs
                )

            # Clean JSON fencing for various LLMs
            content = re.sub(r'^```(?:json)?\s*', '', content, flags=re.MULTILINE)
            content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
            content = content.strip()

            json_start = content.find('{')
            json_end = content.rfind('}')
            if json_start != -1 and json_end != -1:
                content = content[json_start:json_end + 1]

            logger.info("AI response length: %d chars", len(content))

            # Fast path: Try vanilla JSON parse
            try:
                all_playlists = json.loads(content)
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parse failed: {json_err}")
                # FALLBACK: Try repair_json
                try:
                    repaired_content = repair_json(content)
                    all_playlists = json.loads(repaired_content)
                    logger.info("✓ JSON successfully repaired and parsed (json_repair)")
                except Exception as repair_err:
                    # Additional fallback: Regex patch for unterminated strings, common errors
                    logger.warning("repair_json failed, trying additional escapes and truncation")
                    cleaned = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content)
                    cleaned = re.sub(r'[\x00-\x1f]', '', cleaned)  # Remove bad bytes
                    if not cleaned.endswith('}'):
                        cleaned += '}'
                    try:
                        all_playlists = json.loads(cleaned)
                        logger.info("✓ JSON parsed after ad-hoc regex cleanup")
                    except Exception as cleanup_err:
                        # Optionally, try orjson, rapidjson, simplejson, etc. here as fallback
                        # as a last non-fatal resort, truncate at the last }
                        json_end = cleaned.rfind('}')
                        if json_end != -1:
                            try:
                                all_playlists = json.loads(cleaned[:json_end+1])
                                logger.info("✓ JSON parsed after truncating at last brace")
                            except Exception:
                                logger.error("All repair attempts failed.\nProblematic input:\n%s", content[:2000])
                                return {}, "invalid_response"
                        else:
                            logger.error("Could not find valid JSON object at all.")
                            return {}, "invalid_response"

        except Exception as e:
            error_msg = str(e).lower()
            error_type = type(e).__name__

            # Check if it's a rate limit error
            is_rate_limit = any(phrase in error_msg for phrase in [
                'rate limit', 'quota', 'too many requests', '429',
                'resource_exhausted', 'rate_limit_exceeded'
            ]) or 'RateLimitError' in error_type

            if is_rate_limit:
                self.call_count -= 1
                logger.warning("Rate limit error detected - call count rolled back to %d", self.call_count)
                logger.warning("You can retry immediately as this attempt was not recorded")
                logger.error("AI request failed: %s", str(e)[:200])
                return {}, "rate_limit"

            logger.error("AI request failed (counted): %s", str(e)[:200])
            return {}, "api_error"

        if not isinstance(all_playlists, dict):
            logger.error("AI response is not a JSON object")
            return {}, "invalid_response"

        # Validate and clean
        for playlist_name, songs in list(all_playlists.items()):
            if not isinstance(songs, list):
                logger.warning("Invalid format for %s", playlist_name)
                all_playlists[playlist_name] = []
                continue

            valid_songs = [
                song for song in songs
                if isinstance(song, dict) and "artist" in song and "title" in song
            ]
            all_playlists[playlist_name] = valid_songs

        EXPECTED_PLAYLISTS = {
            "Discovery", "Daily Mix 1", "Daily Mix 2", "Daily Mix 3",
            "Daily Mix 4", "Daily Mix 5", "Daily Mix 6",
            "Chill Vibes", "Workout Energy", "Focus Flow", "Drive Time"
        }
        
        # Filter out any hallucinated extra playlists
        unexpected = [k for k in all_playlists if k not in EXPECTED_PLAYLISTS]
        if unexpected:
            logger.warning("AI returned unexpected playlists (filtered): %s", unexpected)
            for k in unexpected:
                del all_playlists[k]

        
        self.response_cache = all_playlists
        self._record_ai_call()
        total = sum(len(songs) for songs in all_playlists.values())
        logger.info("Generated %d playlists (%d songs)", len(all_playlists), total)

        # Persist all new songs for cross-run deduplication
        all_new_songs = [song for songs in all_playlists.values() for song in songs]
        self._save_recent_songs(all_new_songs)

        return all_playlists, None
            
    def _generate_with_retry(self, generate_func, *args, **kwargs) -> str:
        """Retry AI generation with exponential backoff for rate limits and timeouts.
        
        Args:
            generate_func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Generated content string
        """
        max_retries = 3
        base_delay = 10.0
        
        for attempt in range(max_retries):
            try:
                return generate_func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                error_type = type(e).__name__
                
                # Check if it's a rate limit error (works for both Gemini and OpenAI)
                is_rate_limit = any(phrase in error_msg for phrase in [
                    'rate limit', 'quota', 'too many requests', '429', 
                    'resource_exhausted', 'rate_limit_exceeded'
                ]) or 'RateLimitError' in error_type

                # Check if it's a timeout error — cover both exception type names and
                # message-based detection for provider-specific exceptions (e.g. httpx,
                # openai, google-genai) that don't all inherit from TimeoutError.
                # ConnectionError is intentionally excluded because it covers unrelated
                # failures (DNS errors, connection refused, bad AI_BASE_URL) that should
                # fail immediately rather than be retried.
                is_timeout = (
                    isinstance(e, TimeoutError)
                    or 'Timeout' in error_type
                    or any(phrase in error_msg for phrase in [
                        'timed out', 'timeout', 'read timeout',
                        'connect timeout', 'connection timeout',
                    ])
                )
                
                if attempt == max_retries - 1:
                    if is_rate_limit:
                        logger.warning("💡 Tip: Consider using a different AI provider or model with higher limits")
                    elif is_timeout:
                        logger.warning("💡 Tip: Consider increasing AI_REQUEST_TIMEOUT if timeouts persist")
                    raise  # Last attempt, let it fail
                
                if is_rate_limit:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Rate limit hit [%s] (attempt %d/%d). Retrying in %.1fs...",
                        error_type, attempt + 1, max_retries, delay
                    )
                    time.sleep(delay)
                elif is_timeout:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "Request timed out [%s] (attempt %d/%d). Retrying in %.1fs...",
                        error_type, attempt + 1, max_retries, delay
                    )
                    time.sleep(delay)
                else:
                    # Not a rate limit or timeout error, fail immediately
                    logger.error("Non-retryable error: %s", str(e)[:200])
                    raise
        
        raise Exception("Max retries exceeded")

"""TrendForge - Analytics Module

Tracks video generation metrics without YouTube API:
- Topic quality scores
- Hook types used
- Segment analysis  
- Timing data
- Channel association
- Export for analysis
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
ANALYTICS_FILE = Path("./logs/analytics.json")
CHANNEL_FILE = Path("./logs/channel.json")


# Channel management
def set_channel(channel_id: str, channel_name: str = "", channel_link: str = "") -> Dict:
    """Set/associate a YouTube channel with analytics.
    
    Args:
        channel_id: YouTube channel ID
        channel_name: Channel name
        channel_link: Full YouTube channel URL
        
    Returns:
        Channel data dict
    """
    channel_data = {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_link": channel_link,
        "set_at": datetime.now().isoformat()
    }
    
    CHANNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHANNEL_FILE, "w") as f:
        json.dump(channel_data, f, indent=2)
    
    logger.info(f"Channel set: {channel_name or channel_id}")
    return channel_data


def get_channel() -> Optional[Dict]:
    """Get current channel info."""
    if CHANNEL_FILE.exists():
        with open(CHANNEL_FILE) as f:
            return json.load(f)
    return None


def has_channel() -> bool:
    """Check if channel is set."""
    return CHANNEL_FILE.exists()


# Analytics logging
def load_analytics() -> List[Dict]:
    """Load all past analytics."""
    if ANALYTICS_FILE.exists():
        with open(ANALYTICS_FILE) as f:
            return json.load(f)
    return []


def save_analytics(data: List[Dict]):
    """Save analytics to file."""
    ANALYTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def log_generation_start(topic: str, source: str = "user"):
    """Log when generation starts."""
    analytics = load_analytics()
    channel = get_channel()
    
    entry = {
        "id": generate_id(),
        "topic": topic,
        "source": source,
        "channel_id": channel.get("channel_id") if channel else None,
        "channel_name": channel.get("channel_name") if channel else None,
        "start_time": datetime.now().isoformat(),
        "status": "started",
        "segments": [],
        "hooks_variants": [],
        "duration_seconds": 0,
        "error": None,
    }
    
    analytics.append(entry)
    save_analytics(analytics)
    
    return entry["id"]


def log_segment(topic: str, segment_data: Dict):
    """Log segment data for analysis.
    
    Args:
        topic: Video topic
        segment_data: Segment dict with type, text, etc.
    """
    analytics = load_analytics()
    
    # Find latest entry for this topic
    for entry in reversed(analytics):
        if entry.get("topic") == topic and entry.get("status") == "started":
            entry.setdefault("segments", []).append({
                "type": segment_data.get("type"),
                "text_length": len(segment_data.get("text", "")),
                "word_count": len(segment_data.get("text", "").split()),
            })
            break
    
    save_analytics(analytics)


def log_hook(topic: str, hook: str, variant: str = ""):
    """Log hook used.
    
    Args:
        topic: Video topic
        hook: Hook text
        variant: hook type (question/controversy/number)
    """
    analytics = load_analytics()
    
    for entry in reversed(analytics):
        if entry.get("topic") == topic and entry.get("status") == "started":
            if variant:
                entry["hook"] = hook
                entry["hook_type"] = variant
            break
    
    save_analytics(analytics)


def log_completion(topic: str, success: bool, error: str = None, duration: float = 0):
    """Log completion status.
    
    Args:
        topic: Video topic
        success: True if successful
        error: Error message if failed
        duration: Total generation time
    """
    analytics = load_analytics()
    
    for entry in reversed(analytics):
        if entry.get("topic") == topic:
            entry["status"] = "success" if success else "failed"
            entry["end_time"] = datetime.now().isoformat()
            entry["duration_seconds"] = duration
            entry["error"] = error
            
            # Calculate segment stats
            segments = entry.get("segments", [])
            if segments:
                entry["segment_count"] = len(segments)
                entry["total_words"] = sum(s.get("word_count", 0) for s in segments)
                
                # Count by type
                types = {}
                for s in segments:
                    t = s.get("type", "unknown")
                    types[t] = types.get(t, 0) + 1
                entry["segment_types"] = types
            break
    
    save_analytics(analytics)
    logger.info(f"Analytics saved for: {topic} ({'success' if success else 'failed'})")


def get_topic_stats() -> Dict[str, Any]:
    """Get aggregated topic statistics.
    
    Returns:
        Stats dict with counts, top topics, etc.
    """
    analytics = load_analytics()
    
    if not analytics:
        return {"total": 0}
    
    successful = [a for a in analytics if a.get("status") == "success"]
    failed = [a for a in analytics if a.get("status") == "failed"]
    
    # Top topics by attempt count
    topic_counts = {}
    for a in analytics:
        t = a.get("topic", "unknown")
        topic_counts[t] = topic_counts.get(t, 0) + 1
    
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # Average duration
    durations = [a.get("duration_seconds", 0) for a in successful if a.get("duration_seconds")]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    # Hook type distribution
    hook_types = {}
    for a in successful:
        ht = a.get("hook_type", "unknown")
        hook_types[ht] = hook_types.get(ht, 0) + 1
    
    return {
        "total_generations": len(analytics),
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": len(successful) / len(analytics) * 100 if analytics else 0,
        "avg_duration": avg_duration,
        "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        "hook_types": hook_types,
    }


def get_recent_generations(limit: int = 10) -> List[Dict]:
    """Get recent generation data.
    
    Args:
        limit: Number to return
        
    Returns:
        List of analytics entries
    """
    analytics = load_analytics()
    return analytics[-limit:] if analytics else []


def clear_analytics():
    """Clear all analytics data."""
    if ANALYTICS_FILE.exists():
        ANALYTICS_FILE.unlink()
    logger.info("Analytics cleared")


# Helpers
def generate_id() -> str:
    """Generate unique ID."""
    from uuid import uuid4
    return str(uuid4())[:8]


def get_quality_score(topic: str, script_data: Dict = None) -> float:
    """Calculate predicted quality score.
    
    Args:
        topic: Video topic
        script_data: Optional script data
        
    Returns:
        Score 0-100
    """
    score = 50
    
    topic_lower = topic.lower()
    
    # Viral keywords boost
    viral_kw = ["truth", "exposed", "secret", "money", "million", "warning", "ai", "gpt"]
    for kw in viral_kw:
        if kw in topic_lower:
            score += 8
    
    # Script analysis
    if script_data:
        segments = script_data.get("segments", [])
        if segments:
            # More segments = more content
            score += min(20, len(segments) * 3)
            
            # Has hook
            if any(s.get("type") == "hook" for s in segments):
                score += 10
    
    return min(100, score)


# Export for external analysis
def export_csv(filepath: str = "./logs/analytics_export.csv"):
    """Export analytics to CSV.
    
    Args:
        filepath: Output CSV path
    """
    analytics = load_analytics()
    
    if not analytics:
        logger.warning("No analytics to export")
        return
    
    lines = ["topic,source,status,duration_sec,segments,words,hook_type,start_time"]
    
    for a in analytics:
        lines.append(f"{a.get('topic', '')},{a.get('source', '')},{a.get('status', '')},"
                    f"{a.get('duration_seconds', 0)},{a.get('segment_count', 0)},"
                    f"{a.get('total_words', 0)},{a.get('hook_type', '')},{a.get('start_time', '')}")
    
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.write("\n".join(lines))
    
    logger.info(f"Exported to {filepath}")
    return filepath
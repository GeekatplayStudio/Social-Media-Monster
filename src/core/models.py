from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON

class SystemSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key_name: str = Field(unique=True)
    value: str

class TrendItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    url: str
    source: str  # RSS, Reddit, Twitter, HackerNews, GoogleNews
    summary: str
    raw_content: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    score: float = 0.0  # Viral / relevance score
    processed: bool = False

class VerifiedNews(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trend_id: int = Field(foreign_key="trenditem.id")
    headline: str
    verified_facts: str
    source_reliability_score: float = 1.0
    key_takeaways: str  # JSON string or bullet points
    created_at: datetime = Field(default_factory=datetime.now)
    status: str = "verified" # verified, disputed, rejected

class PersonaProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key_name: str = Field(unique=True)
    display_name: str
    humor_level: int = 5       # 0 to 10
    cynicism_level: int = 3    # 0 to 10
    technical_depth: int = 7   # 0 to 10
    political_stance: str = "neutral"
    writing_style: str
    sample_posts: Optional[str] = None  # Uploaded writing samples for voice cloning

class PostDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    verified_news_id: int = Field(foreign_key="verifiednews.id")
    platform: str  # twitter, linkedin, reddit, wordpress, substack, instagram
    persona_key: str
    headline: str
    content: str
    image_prompt: Optional[str] = None
    image_path: Optional[str] = None
    seo_keywords: Optional[str] = None
    ctr_score: float = 0.0
    ai_detection_score: float = 0.0  # Estimated humanization score (lower AI score = more human)
    status: str = "draft"  # draft, approved, published, rejected
    published_at: Optional[datetime] = None
    external_post_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

class SystemLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_name: str
    log_level: str  # INFO, WARNING, ERROR, SUCCESS
    message: str
    details: Optional[str] = None

class PostAnalytics(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="postdraft.id")
    platform: str
    views: int = 0
    likes: int = 0
    shares: int = 0
    comments: int = 0
    ctr: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.now)

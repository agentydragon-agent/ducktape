"""SQLAlchemy models for Gatelet."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey, 
    Boolean, DateTime, func, create_engine, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session

Base = declarative_base()


class WebhookIntegration(Base):
    """Model for webhook integration configurations."""
    
    __tablename__ = "webhook_integrations"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, comment="Integration identifier (e.g., 'home-assistant')")
    description = Column(String, nullable=True)
    auth_type = Column(String, nullable=False, comment="Authentication type (e.g., 'none', 'token', 'basic')")
    auth_config = Column(JSON, nullable=True, comment="Authentication configuration")
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    is_enabled = Column(Boolean, nullable=False, default=True)
    
    # Relationship to webhook payloads
    payloads = relationship("WebhookPayload", back_populates="integration_config")


class WebhookPayload(Base):
    """Model for webhook payloads received by the service."""
    
    __tablename__ = "webhook_payloads"
    
    id = Column(Integer, primary_key=True)
    received_at = Column(DateTime, nullable=False, default=func.now())
    # Direct storage of integration name as it was when received
    integration_name = Column(String, nullable=False, comment="Source integration name when received (e.g., 'home-assistant')")
    # Link to integration configuration
    integration_id = Column(Integer, ForeignKey("webhook_integrations.id"), nullable=True)
    payload = Column(JSON, nullable=False)
    
    # Relationship to integration configuration
    integration_config = relationship("WebhookIntegration", back_populates="payloads")


class AuthKey(Base):
    """Model for authentication keys."""
    
    __tablename__ = "auth_keys"
    
    id = Column(Integer, primary_key=True)
    key_value = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    revoked_at = Column(DateTime, nullable=True)
    
    # Relationship to LLM challenge-response sessions
    cr_sessions = relationship("AuthCRSession", back_populates="auth_key")
    
    def is_valid(self, expiration_seconds: int) -> bool:
        """Check if key is currently valid.
        
        Args:
            expiration_seconds: Number of seconds after creation when key expires
            
        Returns:
            True if key is valid, False otherwise
        """
        now = datetime.now()
        expiration_time = self.created_at + timedelta(seconds=expiration_seconds)
        return self.revoked_at is None and now < expiration_time


class AuthCRSession(Base):
    """Model for Challenge-Response authentication sessions.
    
    These sessions are created when an LLM successfully completes a challenge-response
    authentication and are used to maintain stateful access to protected resources.
    """
    
    __tablename__ = "auth_cr_sessions"
    
    id = Column(Integer, primary_key=True)
    session_token = Column(String, unique=True, nullable=False)
    auth_key_id = Column(Integer, ForeignKey("auth_keys.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    expires_at = Column(DateTime, nullable=False)
    last_activity_at = Column(DateTime, nullable=False, default=func.now())
    
    auth_key = relationship("AuthKey", back_populates="cr_sessions")
    
    @property
    def is_valid(self) -> bool:
        """Check if session is currently valid."""
        now = datetime.now()
        return self.expires_at > now


class AuthNonce(Base):
    """Model for tracking authentication nonces for challenge-response auth."""
    
    __tablename__ = "auth_nonces"
    
    id = Column(Integer, primary_key=True)
    nonce_value = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    
    @property
    def is_valid(self) -> bool:
        """Check if nonce is valid (not used and not expired)."""
        now = datetime.now()
        return self.used_at is None and now < self.expires_at
    
    @property
    def is_used(self) -> bool:
        """Check if nonce has been used."""
        return self.used_at is not None


def get_engine(database_url):
    """Create SQLAlchemy engine."""
    return create_engine(database_url)


def get_session_maker(engine):
    """Create session factory."""
    return sessionmaker(bind=engine)


def get_db(db_url: str) -> Session:
    """Get database session."""
    engine = get_engine(db_url)
    SessionLocal = get_session_maker(engine)
    return SessionLocal()
"""
SQLAlchemy models for the tender type system.

Uses single-table inheritance pattern: Tender + TenderItem tables
with type-specific fields stored as nullable columns + JSON extra_data.
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Tender(Base):
    __tablename__ = "tenders"

    id = Column(Integer, primary_key=True, index=True)
    tender_type = Column(String(20), nullable=False, index=True)
    # not unique on its own: every user has a copy of a tender with its own analysis (E0.14, variant A)
    prozorro_id = Column(String(100), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    expected_cost = Column(Float, nullable=True)
    currency = Column(String(10), default="UAH")
    status = Column(String(20), default="active", index=True)
    customer_name = Column(String(300), nullable=True)
    region = Column(String(100), nullable=True)
    total_amount = Column(Float, nullable=True)

    # Ownership
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Type-specific flags
    warranty_required = Column(Boolean, default=False)         # product
    requires_license = Column(Boolean, default=False)          # service
    project_documentation = Column(Text, nullable=True)        # work

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    items = relationship(
        "TenderItem",
        back_populates="tender",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # named explicitly: the naming convention would only use the first column (uq_tenders_user_id)
    __table_args__ = (UniqueConstraint("user_id", "prozorro_id", name="uq_tenders_user_id_prozorro_id"),)


class TenderItem(Base):
    __tablename__ = "tender_items"

    id = Column(Integer, primary_key=True, index=True)
    tender_id = Column(
        Integer,
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Common fields (all types)
    name = Column(String(500), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_name = Column(String(50), nullable=False)
    unit_price = Column(Float, nullable=True)
    # How unit_price was determined:
    #   'tender'          — taken from Prozorro items[].unit.value.amount or the tender document
    #   'market_estimate' — inferred from live store prices (proxy), because the document had no unit price
    #   'manual'          — user entered the price by hand
    #   'unknown'         — no price available; shown as "—" in UI, excluded from risk analysis
    price_source = Column(String(20), nullable=False, default="tender", server_default="tender")

    # Product-specific
    dk_code = Column(String(50), nullable=True)
    brand = Column(String(200), nullable=True)
    dstu_gost = Column(String(100), nullable=True)
    weight_per_unit_g = Column(Float, nullable=True)
    shelf_life_days = Column(Integer, nullable=True)
    specifications = Column(Text, nullable=True)
    delivery_address = Column(String(500), nullable=True)
    delivery_deadline = Column(String(100), nullable=True)

    # Service-specific
    service_type = Column(String(100), nullable=True)
    period_start = Column(String(50), nullable=True)
    period_end = Column(String(50), nullable=True)
    qualification_requirements = Column(Text, nullable=True)
    sla_description = Column(Text, nullable=True)
    license_required = Column(Boolean, nullable=True)
    location = Column(String(300), nullable=True)

    # Work-specific
    work_type = Column(String(100), nullable=True)
    object_address = Column(String(500), nullable=True)
    estimated_duration_days = Column(Integer, nullable=True)
    technical_specs = Column(Text, nullable=True)
    permit_required = Column(Boolean, nullable=True)
    subcontracting_allowed = Column(Boolean, nullable=True)
    materials_included = Column(Boolean, nullable=True)
    warranty_months = Column(Integer, nullable=True)

    # Flexible storage for future fields
    extra_data = Column(JSON, nullable=True)

    # Relationships
    tender = relationship("Tender", back_populates="items")
    price_history = relationship(
        "PriceHistory",
        back_populates="tender_item",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PriceHistory(Base):
    """Tracks market prices over time for tender items."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer,
        ForeignKey("tender_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price = Column(Float, nullable=False)
    source_store = Column(String(100), nullable=False)
    product_title = Column(String(500), nullable=True)
    product_url = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    tender_item = relationship("TenderItem", back_populates="price_history")

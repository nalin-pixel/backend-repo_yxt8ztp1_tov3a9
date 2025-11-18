"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Literal
from datetime import date

# --------------------------------------------------
# Core domain schemas for the Dubai property platform
# --------------------------------------------------

class Area(BaseModel):
    """
    Areas/Communities collection schema
    Collection name: "area"
    """
    name: str = Field(..., description="Community or Area name, e.g., Al Furjan")
    emirate: str = Field("Dubai", description="Emirate name")
    slug: str = Field(..., description="SEO-friendly slug, unique per area")
    intro: Optional[str] = Field(None, description="Short intro paragraph for the area page")
    description: Optional[str] = Field(None, description="Detailed area guide HTML/Markdown")
    avg_psf: Optional[float] = Field(None, description="Average price per sqft")
    avg_price_1br: Optional[int] = None
    avg_price_2br: Optional[int] = None
    avg_price_3br: Optional[int] = None
    rental_yield_pct: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    tags: Optional[List[str]] = Field(default_factory=list)

class PropertyListing(BaseModel):
    """
    Secondary property listings
    Collection name: "propertylisting" (use lowercased class name)
    """
    # Core
    listing_id: str = Field(..., description="External or internal unique listing identifier")
    status: Literal["Available", "Sold", "Rented", "Off-market"] = "Available"
    transaction_type: Literal["Sale", "Rent"] = "Sale"
    property_type: Literal["Apartment", "Villa", "Townhouse", "Penthouse", "Plot", "Commercial"] = "Apartment"
    bedrooms: Optional[float] = Field(None, description="Allow 0.5 for studio=0, 1.5, etc.")
    bathrooms: Optional[float] = None
    bua_sqft: Optional[int] = Field(None, ge=0)
    price_aed: Optional[int] = Field(None, ge=0)
    service_charges_aed_psf: Optional[float] = None

    # Location
    emirate: str = Field("Dubai")
    area: str = Field(..., description="Community, e.g., Al Furjan")
    building: Optional[str] = Field(None, description="Sub-community or tower name")
    area_slug: Optional[str] = Field(None, description="Slug of the area for linking")
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Marketing / SEO
    title: Optional[str] = Field(None, description="Marketing title shown on cards")
    slug: str = Field(..., description="SEO slug for detail page, must be unique")
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    canonical_url: Optional[str] = None
    description_html: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # Media
    main_image: Optional[HttpUrl] = None
    gallery_images: List[HttpUrl] = Field(default_factory=list)
    floorplan_images: List[HttpUrl] = Field(default_factory=list)
    brochure_url: Optional[HttpUrl] = None

    # Agent / Contact
    agent_name: Optional[str] = None
    agent_photo: Optional[HttpUrl] = None
    agent_rera: Optional[str] = None
    agent_phone: Optional[str] = None
    agent_whatsapp: Optional[str] = None

    # Advanced
    handover_year: Optional[int] = None
    floor: Optional[int] = None
    view: Optional[str] = None

class FAQItem(BaseModel):
    question: str
    answer: str

class PropertyFAQ(BaseModel):
    listing_slug: str = Field(..., description="Slug of the related property listing")
    faqs: List[FAQItem]

# --------------------------------------------------
# Example schemas kept for reference (can be removed later)
# --------------------------------------------------
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True

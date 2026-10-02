from pydantic import BaseModel, ConfigDict


class CopyJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_environment_id: int
    target_environment_id: int
    include_settings: bool = True
    include_suppliers: bool = True
    include_barang: bool = True
    include_photos: bool = True
    include_inventory: bool = False

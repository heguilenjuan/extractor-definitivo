# vendors_registry.py
# Permite aplicar un registro central de "Proveedores" 
# y sus funciones de extraccion especificas.
# Aca se suma nuevos vendedores, sin modificar el core
from typing import Dict, Callable, Any, List

VendorHandler = Callable[[List[str], dict], None]

REGISTRY: Dict[str, VendorHandler] = {}

def register(vendor_id: str):
    
    def deco(fn: VendorHandler):
        REGISTRY[vendor_id.upper()] = fn
        return fn   
    return deco
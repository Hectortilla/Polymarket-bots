from pydantic import BaseModel

from api.catalog.graphs.contracts import NodeGraph


class GraphExample(BaseModel):
    name: str
    description: str
    graph: NodeGraph

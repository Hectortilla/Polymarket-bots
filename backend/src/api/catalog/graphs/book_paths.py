"""Book-field references shared by authored example graphs."""

from api.catalog.graphs.types import GraphFieldPath

BOOK_TOKEN_ID_PATH = GraphFieldPath(segments=("token_id",))
BOOK_BEST_ASK_PRICE_PATH = GraphFieldPath(segments=("best_ask", "price"))
BOOK_BEST_BID_PRICE_PATH = GraphFieldPath(segments=("best_bid", "price"))

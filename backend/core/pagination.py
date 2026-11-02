"""DRF 分页：与 docs/API.md 对齐。

请求：?page=1&size=20（size 可省略，默认 20）。
响应：{"count": n, "results": [...], "page": p, "size": s}
"""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class WPPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "size"
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.count,
                "results": data,
                "page": self.page.number,
                "size": self.page_size,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "results": schema,
                "page": {"type": "integer"},
                "size": {"type": "integer"},
            },
        }

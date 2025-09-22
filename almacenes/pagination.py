# almacenes/pagination.py
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CustomPageNumberPagination(PageNumberPagination):
    page_size = 20  # Valor por defecto
    page_size_query_param = 'page_size'  # Permite ?page_size=10
    max_page_size = 100  # Límite máximo para evitar sobrecarga

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
            'current_page': self.page.number,
            'total_pages': self.page.paginator.num_pages,
            'page_size': self.page_size
        })
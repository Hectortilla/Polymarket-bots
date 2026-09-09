ARG BACKEND_IMAGE
FROM ${BACKEND_IMAGE}
COPY backend/tests/control_plane /app/backend/tests/control_plane
ENV PYTHONPATH=/app/backend/tests

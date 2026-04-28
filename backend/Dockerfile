FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY . .

RUN cmake -B build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build

FROM gcr.io/distroless/cc-debian12:nonroot

LABEL description="Backend C++ Exail V2 - Ultra sécurisé"

COPY --from=builder /build/build/exail_backend /app/exail_backend

EXPOSE 9090

USER nonroot

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["/app/exail_backend", "--health-check"]

ENTRYPOINT ["/app/exail_backend"]

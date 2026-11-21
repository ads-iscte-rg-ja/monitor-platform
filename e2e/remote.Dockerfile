# Imagem do monitor-remote só para os testes ponta a ponta (ADR-0012). O remote é um
# agente instalado em cada host, não um serviço em contentor; esta imagem não é um
# artefacto de produção. Contexto de construção: o repositório monitor-remote.
ARG GO_IMAGE=golang:1.27.4-alpine
FROM ${GO_IMAGE} AS build
# go-sqlite3 precisa de CGO.
RUN apk add --no-cache gcc musl-dev
WORKDIR /src
ENV CGO_ENABLED=1 GOWORK=off
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -trimpath -o /out/agent ./cmd/agent

FROM alpine:3.23
# sqlite: o condutor do E2E lê e altera o buffer com o CLI (estado observado, não logs).
RUN apk add --no-cache ca-certificates sqlite && mkdir /data && chown 65532:65532 /data
COPY --from=build /out/agent /app/agent
USER 65532:65532
WORKDIR /data
ENTRYPOINT ["/app/agent"]

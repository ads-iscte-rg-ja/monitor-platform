# Imagem do monitor-hello-world (aplicação com o SDK) para os testes ponta a ponta
# (ADR-0012). Contexto: o repositório monitor-hello-world; o SDK entra pelo contexto
# adicional "sdk", no mesmo sítio relativo que o replace do go.mod espera.
ARG GO_IMAGE=golang:1.27.4-alpine
FROM ${GO_IMAGE} AS build
RUN apk add --no-cache gcc musl-dev
ENV CGO_ENABLED=1 GOWORK=off
COPY --from=sdk . /src/monitor-go-sdk
WORKDIR /src/monitor-hello-world
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -trimpath -o /out/hello-world .

FROM alpine:3.23
COPY --from=build /out/hello-world /app/hello-world
# O volume do buffer herda o dono desta pasta se for montado aqui primeiro.
RUN mkdir /data && chown 65532:65532 /data
# Mesmo utilizador que o remote: o buffer SQLite é privado (0600) ao dono.
USER 65532:65532
ENTRYPOINT ["/app/hello-world", "-db", "/data/buffer.db"]

# Testes ponta a ponta

**Estado:** por implementar (plano §7, D15; iteração 8).

Docker Compose com `monitor-central`, `monitor-remote` e `monitor-hello-world` construídos a partir dos
repositórios irmãos. Cenários:

| Cenário | Verifica |
|---|---|
| Caminho feliz | logs do hello-world chegam ao central |
| **AV1** | central parado → N logs gerados → central volta → N recebidos, 0 duplicados |
| **AV4** | rajada de logs com o central parado → buffer abaixo do limite, 0 ERROR perdidos |
| **MN1** | registo em quarentena visível no central |

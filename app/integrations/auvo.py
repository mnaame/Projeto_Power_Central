"""Ponto de extensão para a futura integração com o Auvo (abertura
automática de OS quando uma conta entra na lista de "sem comunicação
real") — fora de escopo desta fase (seção 11 do prompt original e
docs/ARQUITETURA.md). Nada aqui é chamado ainda.

Quando for implementada, deve seguir o mesmo padrão de
integrations/telegram_client.py (client HTTP + credenciais próprias,
exceção dedicada que nunca propaga como crash) e ser acionada a partir de
services/alerting.py, no mesmo ponto onde a regra 6.4 decide que uma conta
é nova na lista de sem comunicação (mudança tipo "entrada").
"""

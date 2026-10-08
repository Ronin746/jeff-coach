# Discord webhook — setup e reset (per utente e AI)

Questo file spiega **come** configurare gli alert Discord dello scanner.
**Non contiene** l’URL del webhook. L’URL va solo in `DISCORD_WEBHOOK_URL` (secret).

## Per un AI che riprende questo progetto

Se `python discord_notify.py --check` stampa `webhook_missing`, oppure i POST falliscono (401/404):

1. **Non** cercare l’URL in chat, git, log o backup.
2. Spiega all’utente che serve un webhook Discord fresco.
3. Chiedi il secret con input mascherato (`DISCORD_WEBHOOK_URL`).
4. Verifica con `--check` → `webhook_ok` senza stampare l’URL.
5. Solo se l’utente dice sì: messaggio di test `🧪 TEST scanner…` sul canale.
6. In RTH: postare **solo** segnali CONFIRMED **nuovi**; se nessuno → silenzio.

Prompt breve da usare con l’utente:

```
Il webhook Discord non è impostato (o non è più valido).
Per rimetterlo:
1) Discord → canale alert → Modifica canale → Integrazioni → Webhook
2) Nuovo webhook (o Rigenera URL) → Copia URL webhook
3) Incollalo nel campo secret mascherato (nome: DISCORD_WEBHOOK_URL)
Non incollarlo in chiaro in chat.
```

## Per l’utente — creazione passo-passo

1. Apri Discord e vai al **server** dove vuoi gli alert.
2. Sul canale di testo (es. `#scanner`) apri **Modifica canale**.
3. Vai su **Integrazioni** → **Webhook**.
4. **Nuovo webhook** (oppure seleziona quello esistente e **Copia URL** / **Rigenera**).
5. Nome consigliato: `Intraday Trading Scanner`.
6. Controlla che il canale selezionato sia quello giusto.
7. **Copia URL webhook** — formato tipico:
   `https://discord.com/api/webhooks/<id>/<token>`
8. Consegnarlo all’assistente **solo** come secret/env `DISCORD_WEBHOOK_URL`.
9. Per disattivare: elimina il webhook su Discord (gli URL vecchi smettono di funzionare).

## Dove lo legge il codice

File: `/workspace/tv-scanner/discord_notify.py` → `load_webhook_url()`:

1. `os.environ["DISCORD_WEBHOOK_URL"]`
2. altrimenti `/home/box/agent-data/box-secrets.json` → `card.DISCORD_WEBHOOK_URL`

## Regole di invio (non cambiare senza chiedere)

- Solo Trigger A/B **nuovi** (dedupe `symbol|trigger|bar_t`).
- Se lista vuota → **non** chiamare il webhook.
- Non includere l’URL nei markdown di backup né nel tarball come valore in chiaro.

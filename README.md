# Auto Template — plugin per DaVinci Resolve

Analizza un video caricato (tagli, spazi vuoti, testi a schermo, voce/musica,
effetti/transizioni) e costruisce automaticamente una timeline equivalente in
DaVinci Resolve — lo stesso concetto dei modelli di CapCut, ma usando l'editor
nativo di Resolve invece di reinventarne uno.

Nessun cloud, nessun account: tutto locale sul tuo PC. L'analisi AI usa di default
un modello vision **locale e gratuito** (via [Ollama](https://ollama.com)), senza
costi né limiti di richieste.

> 👉 **Prima volta qui?** Segui la
> [**Guida completa all'installazione**](GUIDA_INSTALLAZIONE_DETTAGLIATA.md) —
> spiega ogni passo, click per click, anche se non hai mai usato un terminale.
> Questo README è una panoramica più tecnica.

## Contatti

Domande, problemi, suggerimenti: **gdciateam@gmail.com**. Nonostante
l'indirizzo contenga "ia", a rispondere alle email è una persona reale (io),
non un'intelligenza artificiale generica.

## Architettura (perché un comando da terminale + uno script Lua)

Due scoperte fatte testando su Resolve reale hanno determinato questa architettura,
entrambe verificate interattivamente (non solo lette in documentazione):

1. **DaVinci Resolve 21.1** ha spostato l'esecuzione di script Python dal menu
   Script in esclusiva per Resolve **Studio**: sulla versione Free, i file `.py`
   non compaiono più affatto nel menu Script (i file `.lua` sì).
2. **L'ambiente di scripting Lua di Resolve non ha `io` né `os.execute`
   funzionanti** (e nemmeno le alternative `bmd.readfile`/`writefile`/`execute`) —
   né dalla Console né dagli script lanciati dal menu. Uno script Lua dentro
   Resolve quindi **non può leggere né scrivere file, né lanciare programmi
   esterni**. Questo non è specifico della Free: è come funziona lo scripting Lua
   di Resolve in generale.

La conseguenza pratica: uno script Lua dentro Resolve non può da solo chiamare
Python, leggere un `template.json`, o generare le clip segnaposto. Per questo il
flusso è diviso in due fasi, con i ruoli scambiati rispetto al design più ovvio:

- **Fase 1 — un comando Python che lanci tu, da terminale** (`resolve_plugin.build_project`):
  fa tutta l'analisi AI (tagli, testi, voce/musica), genera tutte le clip
  segnaposto e i file sottotitoli sul disco, e infine **scrive un file `.lua`
  completo e pronto** — con ogni valore già calcolato e incorporato come
  letterale — direttamente nella cartella Script di Resolve. Un processo Python
  normale non ha nessuna delle restrizioni di cui sopra.
- **Fase 2 — dentro Resolve**: apri il menu Script e lanci lo script appena
  generato. Non deve leggere né scrivere nulla, né lanciare nulla: si limita a
  chiamare l'API di Resolve con i valori già pronti.

Ogni video analizzato genera un proprio script con un nome dedicato (es.
`Auto Template - mio_video_20260916_143000.lua`), quindi il menu Script di Resolve
funge anche da lista dei "progetti pronti da costruire".

Funziona così sia su Resolve **Free** che **Studio**.

## Requisiti

- Windows + DaVinci Resolve (Free o Studio).
- Python 3.10+ installato e disponibile nel PATH.
- [FFmpeg](https://ffmpeg.org/download.html) nel PATH (usato per rilevare tagli,
  spazi vuoti/silenzi e per generare le clip segnaposto dei gap).
- [Ollama](https://ollama.com) installato, per l'analisi AI locale e gratuita
  (in alternativa: una API key gratuita di Google Gemini, vedi sotto).
- Facoltativo: [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) nel PATH,
  usato come riconoscimento testo offline aggiuntivo.
- La separazione voce/musica (vedi sotto) usa Whisper via `faster-whisper`, incluso
  in `requirements.txt`: gira su CPU, non serve una GPU né una API key.

## Installazione

```powershell
pip install -r requirements.txt
python scripts/install.py
```

Copia il codice Python del plugin in una cartella privata
(`%APPDATA%\AutoTemplatePlugin`) e prepara un comando pronto all'uso,
`run_build.py`, nella stessa cartella. L'output di `install.py` mostra il comando
esatto da usare — tienilo a portata di mano per il passo successivo.

## Configurare il backend AI

Di default il plugin usa **Ollama** (locale, gratuito, offline):

```powershell
ollama pull qwen2.5vl
```

Su hardware con poca VRAM, usa un modello più leggero modificando
`resolve_plugin/user_config.json` (crealo se non esiste):

```json
{ "ollama": { "model": "moondream" } }
```

`ollama serve` deve essere in esecuzione (di solito parte automaticamente dopo
l'installazione di Ollama).

**Alternativa opzionale**: Google Gemini free tier (limiti di richieste stretti,
serve una API key gratuita da [Google AI Studio](https://aistudio.google.com)):

```json
{ "ai_backend": "gemini", "gemini": { "api_key": "LA-TUA-CHIAVE" } }
```

## Come si usa

1. Apri Resolve, apri o crea un progetto (deve restare aperto per il passo 3).
2. Da PowerShell, lancia (percorso esatto mostrato da `install.py`):
   ```powershell
   python "%APPDATA%\AutoTemplatePlugin\run_build.py" "C:\percorso\del\tuo\video.mp4"
   ```
   Segui l'avanzamento direttamente nel terminale (rilevamento tagli → spazi vuoti
   → voce/musica → analisi AI per clip). Per un video sotto i 2 minuti aspettati da
   qualche decina di secondi a un paio di minuti, in base a GPU/CPU. Alla fine il
   comando stampa il nome esatto dello script generato.
3. In Resolve: **Workspace > Scripts > Edit** (in italiano: **Spazio lavoro > Script
   > Edit**) → lancia la voce **"Auto Template - ..."** appena creata (riapri il
   menu se non la vedi subito).
4. Lo script costruisce **automaticamente** una nuova timeline nel progetto Resolve
   corrente, che replica: tagli, spazi vuoti (come clip segnaposto nere), testi a
   schermo (tracca sottotitoli "Testo a schermo"), il parlato trascritto (tracca
   sottotitoli separata "Dialogo (trascrizione)"), voce e musica su due tracce audio
   dedicate ("Voce"/"Musica") e marker gialli dove è stato rilevato un
   effetto/transizione o un possibile cambio di canzone.
5. Esporta normalmente dalla pagina **Deliver** di Resolve — il rendering finale è
   sempre quello nativo di Resolve, il plugin non tocca l'export.

> **Nota**: la sostituzione delle clip del template con i tuoi video (tramite le
> Take di Resolve) era già implementata in una versione precedente del plugin ma
> non è ancora stata riportata in questa architettura — vedi "Limiti noti" sotto.

## Separazione voce/musica e trascrizione (dialogo)

Questa funzione è **indipendente** da quella dei testi a schermo (punto precedente):
legge cosa viene **detto** nell'audio (via Whisper), non cosa è **scritto** nell'immagine
(via OCR/AI vision). I due percorsi non si toccano mai: campi diversi nel template
interno (`texts` per i testi a schermo, `dialogue`/`voice_segments`/`music_segments`
per il parlato), file .srt separati, tracce Resolve separate e rinominate — così non
puoi ritrovarti scritte a schermo mischiate ai sottotitoli del parlato o viceversa.

Cosa succede in pratica quando lo script Lua costruisce la timeline:
- **Traccia audio "Voce"**: un blocco per ogni intervento parlato rilevato da Whisper,
  con la durata esatta di quell'intervento — esattamente il "box separato" richiesto.
- **Traccia audio "Musica"**: un blocco continuo per tutto ciò che non è parlato,
  salvo che venga segnalato un possibile cambio di canzone (vedi sotto).
- **Traccia sottotitoli "Dialogo (trascrizione)"**: la trascrizione testuale di ogni
  intervento parlato, con gli stessi tempi — separata dalla traccia "Testo a schermo".

Limiti onesti da conoscere:
- **Non è vera separazione audio (niente rimozione della voce dalla musica)**: i blocchi
  "Voce" e "Musica" sono ritagli temporali dello **stesso** audio originale misto — se nel
  video si parla sopra una base musicale, quella musica resta udibile anche nel blocco
  "Voce" in quel punto. Una vera isolazione vocale richiederebbe un modello molto più
  pesante (es. Demucs), fuori dall'obiettivo "gratuito e leggero" del progetto.
- **Il "possibile cambio musica" è un'euristica sul volume**, non un vero riconoscimento
  di canzoni: rileva salti di intensità sonora sostenuti e li segna con un marker giallo
  da verificare a orecchio — non taglia mai automaticamente la traccia musica, per evitare
  tagli sbagliati nel posto sbagliato.
- Whisper gira su CPU (modello `base` di default, configurabile in `user_config.json`
  con `"whisper_model_size"`) e rileva/trascrive automaticamente qualsiasi lingua.
- Puoi disattivare del tutto questa analisi (se non ti serve o vuoi accelerare
  l'elaborazione) impostando in `user_config.json`: `{ "enable_speech_analysis": false }`.

## Limiti noti

- **La sostituzione clip con le Take non è ancora disponibile in questa architettura.**
  Era già implementata (vedi `resolve_plugin/resolve_api/takes_manager.py`, ancora nel
  repo) in una versione precedente del plugin che lanciava Python direttamente da
  Resolve; con l'attuale generazione di script Lua statici va riscritta di
  conseguenza — è il prossimo pezzo pianificato.
- **Le transizioni non vengono riapplicate automaticamente**: l'API di scripting di
  Resolve non permette di aggiungere transizioni via codice. Compaiono come marker
  gialli sulla timeline con un'etichetta (es. "cross dissolve") da applicare a mano
  trascinando l'effetto da Resolve.
- **I testi rilevati (a schermo e dialogo) appaiono come tracce sottotitoli**, non come
  Text+ nativo — è il meccanismo di scripting più stabile per avere i tempi esatti. Puoi
  convertirli o restilizzarli manualmente in Text+ dopo la generazione.
- **Zoom/pan/velocità**: lo schema del template (`TransformEffect`) supporta già
  queste proprietà (applicate via `TimelineItem:SetProperty` nello script generato),
  ma il rilevamento automatico di questi effetti dal video sorgente non è ancora
  implementato nella pipeline di analisi — al momento vengono rilevati solo testo ed
  etichette di stile/effetto generiche. È un'estensione naturale per una versione
  successiva.
- **Due passaggi invece di uno**: comando da terminale, poi script da Resolve —
  conseguenza diretta del sandboxing Lua descritto sopra, non è evitabile restando
  gratuiti (Resolve Studio rimuoverebbe entrambe le restrizioni e permetterebbe di
  tornare a un flusso Python-in-Resolve a un solo passaggio).
- Progetto pensato per un solo utente/una sola macchina: niente account, niente
  sincronizzazione multi-dispositivo.

## Test automatici

```powershell
pip install -r requirements.txt
pytest
```

I test coprono la pipeline di analisi (rilevamento tagli/gap, classificazione AI,
storage progetti), la preparazione di clip segnaposto/sottotitoli
(`media_prep.py`), il generatore di script Lua (`lua_codegen.py`), il comando
`build_project.py` e lo script di installazione — non richiedono Resolve né Ollama
installati.

Se hai un interprete Lua 5.1-compatibile sul PATH (`lua5.1`, `lua` o `luajit`),
`pytest` esegue anche un test end-to-end che fa girare **realmente** uno script Lua
generato contro un finto ambiente Resolve con `io`/`os.execute` volutamente
disabilitati (`tests/lua_stub_harness.lua`) — la stessa condizione della sandbox
reale — verificando l'intera sequenza di chiamate all'API. Se non hai un
interprete Lua installato, questo singolo test viene saltato automaticamente, il
resto della suite gira comunque.

Una copia legacy della logica di traduzione template→Resolve in Python resta in
`resolve_plugin/resolve_api/` (con relativi test) da quando il plugin lanciava
Python direttamente da Resolve — non più usata dal flusso attuale, tenuta come
riferimento/riserva (funzionerebbe su Resolve Studio, dove Python non è ristretto).

## Checklist di verifica manuale (da fare su Windows con Resolve)

Questa integrazione con l'app desktop non è testabile in modo completamente
automatico: dopo l'installazione, verifica a mano che:

- [ ] Il comando `python ...\run_build.py <video>` completi senza errori e stampi
      il nome dello script generato.
- [ ] Nella cartella `%USERPROFILE%\AutoTemplateProjects\` compaia una sottocartella
      per il progetto, con dentro `source_video.*` e le clip segnaposto/sottotitoli.
- [ ] In Resolve, **Workspace > Scripts > Edit** mostri la nuova voce
      "Auto Template - ...".
- [ ] Lanciandola, Resolve crei automaticamente una nuova timeline nel progetto corrente.
- [ ] I tagli sulla timeline generata corrispondano a quelli del video originale.
- [ ] Gli spazi vuoti rilevati appaiano come clip nere segnaposto della giusta durata.
- [ ] Se il video aveva testo a schermo, compaia una tracca sottotitoli "Testo a schermo" con i tempi giusti.
- [ ] Se il video aveva parlato, compaiano due tracce audio "Voce"/"Musica" e una tracca sottotitoli "Dialogo (trascrizione)" separata da quella del testo a schermo.
- [ ] Se il video aveva transizioni (o un cambio di canzone), compaiano marker gialli nei punti giusti.

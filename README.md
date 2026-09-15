# Auto Template — plugin per DaVinci Resolve

Analizza un video caricato (tagli, spazi vuoti, testi a schermo, effetti/transizioni)
e costruisce automaticamente una timeline equivalente in DaVinci Resolve, con la
possibilità di sostituire ogni clip del "template" generato con un proprio video —
lo stesso concetto dei modelli di CapCut, ma usando l'editor nativo di Resolve invece
di reinventarne uno.

Nessun cloud, nessun account: tutto locale sul tuo PC. L'analisi AI usa di default
un modello vision **locale e gratuito** (via [Ollama](https://ollama.com)), senza
costi né limiti di richieste.

## Architettura (perché Lua + Python)

DaVinci Resolve **21.1** ha spostato l'esecuzione di script Python dal menu Scripts
in esclusiva per Resolve **Studio**: sulla versione Free, i file `.py` non compaiono
più affatto nel menu Script. Lo scripting **Lua** invece non è soggetto a questa
restrizione, su nessuna delle due edizioni. Per questo il plugin è diviso in due parti:

- **`lua/Auto Template.lua`** — l'unica cosa che vedi dentro Resolve. Chiede il video,
  lancia l'analisi (vedi sotto) e costruisce la timeline usando l'API di scripting di
  Resolve. Nessuna finestra grafica con lista progetti: essendo anche l'interfaccia
  UIManager riservata a Resolve Studio, la selezione video avviene con la finestra di
  scelta file standard di Resolve.
- **`resolve_plugin/` (Python)** — tutta l'analisi AI (tagli, testi, voce/musica).
  Non tocca mai l'API di Resolve, quindi non è soggetta alla restrizione: lo script
  Lua lo lancia come processo esterno e legge il risultato (`template.json`).

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

Lo script di installazione copia il codice Python del plugin in una cartella privata
(`%APPDATA%\AutoTemplatePlugin`) e installa **`Auto Template.lua`** dentro la cartella
Scripts di Resolve (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit`).
Riavvia Resolve: troverai la voce **Workspace > Scripts > Edit > Auto Template**
(in italiano: **Spazio lavoro > Script > Edit > Auto Template**). Nota: le versioni
di Resolve più recenti (21+) hanno rimosso la categoria generica "Utility" a favore
delle sole categorie legate alle pagine (Comp/Edit/Color/Deliver) — per questo lo
script viene installato sotto "Edit".

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

1. Apri Resolve, apri o crea un progetto.
2. **Workspace > Scripts > Edit > Auto Template** (in italiano: **Spazio lavoro > Script > Edit > Auto Template**).
3. Si apre la finestra di selezione file standard di Resolve: scegli il video da
   analizzare. Il progetto viene salvato in `%USERPROFILE%\AutoTemplateProjects\<nome>_<data>\`.
4. L'analisi parte subito (nessuna finestra di progresso: segui l'avanzamento nella
   **Console** di Resolve — Workspace > Console / "Terminale" — dove lo script stampa
   ogni fase: rilevamento tagli → spazi vuoti → voce/musica → analisi AI per clip).
   Per un video sotto i 2 minuti aspettati da qualche decina di secondi a un paio di
   minuti, in base a GPU/CPU.
5. A fine analisi lo script costruisce **automaticamente** una nuova timeline nel
   progetto Resolve corrente, che replica: tagli, spazi vuoti (come clip segnaposto
   nere), testi a schermo (tracca sottotitoli "Testo a schermo"), il parlato
   trascritto (tracca sottotitoli separata "Dialogo (trascrizione)"), voce e
   musica su due tracce audio dedicate ("Voce"/"Musica") e marker gialli dove è
   stato rilevato un effetto/transizione o un possibile cambio di canzone.
6. Esporta normalmente dalla pagina **Deliver** di Resolve — il rendering finale è
   sempre quello nativo di Resolve, il plugin non tocca l'export.

> **Nota**: la sostituzione delle clip del template con i tuoi video (tramite le
> Take di Resolve) era già implementata nella prima versione Python del plugin ma
> non è ancora stata riportata nella versione Lua — vedi "Limiti noti" sotto.

## Separazione voce/musica e trascrizione (dialogo)

Questa funzione è **indipendente** da quella dei testi a schermo (punto precedente):
legge cosa viene **detto** nell'audio (via Whisper), non cosa è **scritto** nell'immagine
(via OCR/AI vision). I due percorsi non si toccano mai: campi diversi in `template.json`
(`texts` per i testi a schermo, `dialogue`/`voice_segments`/`music_segments` per il
parlato), file .srt separati, tracce Resolve separate e rinominate — così non puoi
ritrovarti scritte a schermo mischiate ai sottotitoli del parlato o viceversa.

Cosa succede in pratica quando costruisci la timeline:
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

- **La sostituzione clip con le Take non è ancora disponibile nella versione Lua.**
  Era già implementata (vedi `resolve_plugin/resolve_api/takes_manager.py`) quando
  il plugin lanciava Python direttamente da Resolve; con il passaggio obbligato a
  Lua (per via della restrizione Studio-only di Resolve 21.1 su Python) questa parte
  va riscritta in Lua — è il prossimo pezzo pianificato.
- **Le transizioni non vengono riapplicate automaticamente**: l'API di scripting di
  Resolve non permette di aggiungere transizioni via codice. Compaiono come marker
  gialli sulla timeline con un'etichetta (es. "cross dissolve") da applicare a mano
  trascinando l'effetto da Resolve.
- **I testi rilevati (a schermo e dialogo) appaiono come tracce sottotitoli**, non come
  Text+ nativo — è il meccanismo di scripting più stabile per avere i tempi esatti. Puoi
  convertirli o restilizzarli manualmente in Text+ dopo la generazione.
- **Zoom/pan/velocità**: lo schema del template (`TransformEffect`) supporta già
  queste proprietà (`TimelineItem.SetProperty`, applicata anche dallo script Lua), ma
  il rilevamento automatico di questi effetti dal video sorgente non è ancora
  implementato nella pipeline di analisi — al momento vengono rilevati solo testo ed
  etichette di stile/effetto generiche. È un'estensione naturale per una versione
  successiva.
- **Nessuna finestra con lista progetti**: l'interfaccia grafica UIManager di Resolve
  è anch'essa riservata a Resolve Studio, quindi non è utilizzabile su Free. Ogni
  progetto resta comunque salvato su disco in `%USERPROFILE%\AutoTemplateProjects\`.
- Progetto pensato per un solo utente/una sola macchina: niente account, niente
  sincronizzazione multi-dispositivo.

## Test automatici

```powershell
pip install -r requirements.txt
pytest
```

I test coprono la pipeline di analisi (rilevamento tagli/gap, classificazione AI,
storage progetti), il wrapper da riga di comando (`analyze_cli.py`) e lo script di
installazione — non richiedono Resolve né Ollama installati.

Lo script `lua/Auto Template.lua` non è coperto da `pytest` (linguaggio diverso), ma
ha un test dedicato che simula Resolve e Python con degli stub e verifica l'intera
logica di costruzione della timeline:

```bash
lua5.1 tests/lua_smoke_test.lua   # oppure `lua`/`luajit`, a seconda di cosa hai
```

Una copia legacy della logica di traduzione template→Resolve in Python resta in
`resolve_plugin/resolve_api/` (con relativi test) da quando il plugin lanciava
Python direttamente da Resolve — non più usata dal flusso attuale (Lua), tenuta
come riferimento/riserva in caso di aggiornamenti futuri di Resolve.

## Checklist di verifica manuale (da fare su Windows con Resolve)

Questa integrazione con l'app desktop non è testabile in modo completamente
automatico: dopo l'installazione, verifica a mano che:

- [ ] La voce **Workspace > Scripts > Edit > Auto Template** appaia nel menu.
- [ ] Cliccandoci sopra si apra la finestra di selezione file di Resolve.
- [ ] Dopo aver scelto un video, l'analisi parta (messaggi visibili nella Console di Resolve).
- [ ] Al termine, Resolve crei automaticamente una nuova timeline nel progetto corrente.
- [ ] I tagli sulla timeline generata corrispondano a quelli del video originale.
- [ ] Gli spazi vuoti rilevati appaiano come clip nere segnaposto della giusta durata.
- [ ] Se il video aveva testo a schermo, compaia una tracca sottotitoli "Testo a schermo" con i tempi giusti.
- [ ] Se il video aveva parlato, compaiano due tracce audio "Voce"/"Musica" e una tracca sottotitoli "Dialogo (trascrizione)" separata da quella del testo a schermo.
- [ ] Se il video aveva transizioni (o un cambio di canzone), compaiano marker gialli nei punti giusti.

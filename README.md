# Auto Template — plugin per DaVinci Resolve

Analizza un video caricato (tagli, spazi vuoti, testi a schermo, effetti/transizioni)
e costruisce automaticamente una timeline equivalente in DaVinci Resolve, con la
possibilità di sostituire ogni clip del "template" generato con un proprio video —
lo stesso concetto dei modelli di CapCut, ma usando l'editor nativo di Resolve invece
di reinventarne uno.

Nessun cloud, nessun account: tutto locale sul tuo PC. L'analisi AI usa di default
un modello vision **locale e gratuito** (via [Ollama](https://ollama.com)), senza
costi né limiti di richieste.

## Requisiti

- Windows + DaVinci Resolve (Free o Studio).
- Python 3.10+ installato e disponibile nel PATH (lo stesso interprete che configuri
  in Resolve: Preferences > System > General > "Scripting").
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

Lo script di installazione copia il codice del plugin in una cartella privata
(`%APPDATA%\AutoTemplatePlugin`) e crea un unico file lanciatore dentro la cartella
Scripts di Resolve (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`).
Riavvia Resolve: troverai la voce **Workspace > Scripts > Utility > Auto Template**.

Assicurati che in Resolve, sotto **Preferences > System > General**, lo scripting
sia abilitato (impostazione "External scripting using" — su Resolve Free gli script
funzionano comunque solo se lanciati dal menu Scripts di Resolve stesso, non da un
terminale esterno: è esattamente così che questo plugin è pensato per funzionare).

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
2. **Workspace > Scripts > Utility > Auto Template**.
3. **Carica video...** → scegli il video sorgente. Il progetto viene salvato in
   `%USERPROFILE%\AutoTemplateProjects\<id>\` e l'analisi parte in background
   (stato mostrato in fondo alla finestra: rilevamento tagli → spazi vuoti →
   analisi AI per clip).
4. A fine analisi, seleziona il progetto e clicca **Costruisci timeline**: Resolve
   crea una nuova timeline che replica tagli, spazi vuoti (come clip segnaposto
   nere), testi a schermo (tracca sottotitoli "Testo a schermo"), il parlato
   trascritto (tracca sottotitoli separata "Dialogo (trascrizione)"), voce e
   musica su due tracce audio dedicate ("Voce"/"Musica") e marker gialli dove è
   stato rilevato un effetto/transizione o un possibile cambio di canzone.
5. Nella sezione **Sostituisci con i miei video**, seleziona una clip dalla lista e
   **Assegna video a questa clip**: il tuo video viene aggiunto come "Take"
   alternativo sullo stesso slot (durata, posizione ed effetti restano quelli del
   template) e selezionato automaticamente.
6. Esporta normalmente dalla pagina **Deliver** di Resolve — il rendering finale è
   sempre quello nativo di Resolve, il plugin non tocca l'export.

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

- **Le transizioni non vengono riapplicate automaticamente**: l'API di scripting di
  Resolve non permette di aggiungere transizioni via codice. Compaiono come marker
  gialli sulla timeline con un'etichetta (es. "cross dissolve") da applicare a mano
  trascinando l'effetto da Resolve.
- **I testi rilevati (a schermo e dialogo) appaiono come tracce sottotitoli**, non come
  Text+ nativo — è il meccanismo di scripting più stabile per avere i tempi esatti. Puoi
  convertirli o restilizzarli manualmente in Text+ dopo la generazione.
- **Zoom/pan/velocità**: lo schema del template (`TransformEffect`) supporta già
  queste proprietà (`TimelineItem.SetProperty`), ma il rilevamento automatico di
  questi effetti dal video sorgente non è ancora implementato nella pipeline di
  analisi — al momento vengono rilevati solo testo ed etichette di stile/effetto
  generiche. È un'estensione naturale per una versione successiva.
- Progetto pensato per un solo utente/una sola macchina: niente account, niente
  sincronizzazione multi-dispositivo.

## Test automatici

```powershell
pip install -r requirements.txt
pytest
```

I test coprono la pipeline di analisi (rilevamento tagli/gap, classificazione AI,
storage progetti) e la logica di traduzione template→Resolve (`resolve_api/`) con
un mock dell'API di Resolve — non richiedono Resolve né Ollama installati.

## Checklist di verifica manuale (da fare su Windows con Resolve)

Questa integrazione con l'app desktop non è testabile in modo automatico: dopo
l'installazione, verifica a mano che:

- [ ] La voce **Workspace > Scripts > Utility > Auto Template** appaia e apra la finestra.
- [ ] **Carica video...** apra un file dialog e crei un progetto nella lista.
- [ ] Lo stato di analisi avanzi (tagli → spazi vuoti → analisi per clip) fino a "Analisi completata".
- [ ] **Costruisci timeline** crei davvero una nuova timeline nel progetto Resolve corrente.
- [ ] I tagli sulla timeline generata corrispondano a quelli del video originale.
- [ ] Gli spazi vuoti rilevati appaiano come clip nere segnaposto della giusta durata.
- [ ] Se il video aveva testo a schermo, compaia una tracca sottotitoli "Testo a schermo" con i tempi giusti.
- [ ] Se il video aveva parlato, compaiano due tracce audio "Voce"/"Musica" e una tracca sottotitoli "Dialogo (trascrizione)" separata da quella del testo a schermo.
- [ ] Se il video aveva transizioni (o un cambio di canzone), compaiano marker gialli nei punti giusti.
- [ ] **Assegna video a questa clip** aggiunga il video scelto come Take e lo selezioni
      (visibile nell'Inspector della clip, sezione Take Selector).

# CubeMine Pix — App Flutter

Telas iniciais do app (Fase 1): cadastro/login, tela do cubo (assistir
anúncio → aguardar confirmação → minerar → coletar) e carteira. Consome os
módulos já implementados no backend (auth, wallet, ads, mining, cubes). Saque
Pix, missões e admin ficam para a Fase 2/3.

## Antes de rodar: configurar o Firebase

O app usa Firebase Auth (seção 2) mas ainda **não** está conectado a um
projeto Firebase real. Antes de rodar contra um backend de verdade:

```bash
dart pub global activate flutterfire_cli
flutterfire configure
```

Isso gera `lib/firebase_options.dart` e os arquivos nativos
(`google-services.json` / `GoogleService-Info.plist`) a partir do seu
projeto Firebase. Sem isso, `main.dart` captura o erro de inicialização e o
app sobe, mas login/cadastro falham em runtime.

## Configuração da URL do backend

```bash
flutter run --dart-define=API_BASE_URL=http://SEU_HOST:8000
```

Sem o `--dart-define`, o default (`lib/core/api_config.dart`) aponta para
`http://10.0.2.2:8000`, que é o host da máquina a partir do emulador Android.

## Estrutura

```
lib/
  core/        # ApiClient (anexa o Bearer token), AuthService (Firebase Auth)
  models/      # DTOs espelhando os schemas do backend
  services/    # um Api por módulo do backend (interface + impl HTTP)
  controllers/ # MiningController -- estado do ciclo do cubo
  screens/     # auth/, cube/, wallet/, home/ (shell com bottom nav)
  theme/       # paleta neon azul/roxo/preto/branco
  widgets/     # componentes visuais reutilizáveis
```

## Rodando

```bash
flutter pub get
flutter run
```

## Testes

```bash
flutter analyze
flutter test
```

Os testes usam fakes das interfaces `AuthService`/`AuthApi`/`CubesApi`/
`AdsApi`/`MiningApi`/`WalletApi` (em `test/fakes/`) -- não dependem de
Firebase real nem de um backend rodando.

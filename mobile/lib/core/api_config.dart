/// URL base do backend FastAPI.
///
/// Default (sem nenhum --dart-define): a API de produção na Render, usada
/// em builds normais (ex: `flutter build apk`).
///
/// Para desenvolvimento local contra o backend rodando na própria máquina,
/// passe explicitamente (10.0.2.2 é o endereço que o emulador Android usa
/// para alcançar o localhost do host):
/// `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000`
class ApiConfig {
  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://cubemine-pix-api.onrender.com',
  );
}

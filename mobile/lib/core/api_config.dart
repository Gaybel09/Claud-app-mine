/// URL base do backend FastAPI. Sobrescrita em build/run via
/// `--dart-define=API_BASE_URL=https://...` -- o valor abaixo é só o default
/// de desenvolvimento local (emulador Android usa 10.0.2.2 para o host).
class ApiConfig {
  static const baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );
}

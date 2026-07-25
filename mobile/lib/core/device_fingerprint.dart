import 'dart:math';

import 'package:shared_preferences/shared_preferences.dart';

/// Fingerprint básico de device (antifraude, seção 11 do backend): um UUID
/// v4 gerado uma única vez na primeira execução do app e persistido em
/// disco (shared_preferences), reaproveitado em todas as sessões seguintes
/// do mesmo app instalado. Não precisa ser estável entre reinstalações --
/// só entre sessões do mesmo install.
///
/// É só telemetria interna, mandada ao backend via header X-Device-Id (ver
/// ApiClient) -- nunca mostrado em nenhuma tela.
abstract class DeviceFingerprint {
  Future<String> getDeviceId();
}

class SharedPreferencesDeviceFingerprint implements DeviceFingerprint {
  static const _storageKey = 'device_id';

  String? _cached;

  @override
  Future<String> getDeviceId() async {
    final cached = _cached;
    if (cached != null) return cached;

    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_storageKey);
    if (existing != null) {
      _cached = existing;
      return existing;
    }

    final generated = _generateUuidV4();
    await prefs.setString(_storageKey, generated);
    _cached = generated;
    return generated;
  }
}

/// UUID v4 (RFC 4122) a partir de bytes aleatórios criptograficamente
/// seguros -- sem depender do pacote `uuid` só para isso.
String _generateUuidV4() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // versão 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante RFC 4122

  String hex(int start, int end) =>
      bytes.sublist(start, end).map((b) => b.toRadixString(16).padLeft(2, '0')).join();

  return '${hex(0, 4)}-${hex(4, 6)}-${hex(6, 8)}-${hex(8, 10)}-${hex(10, 16)}';
}

/// Instância única do app inteiro -- mesma ideia dos singletons já usados
/// no backend (ex: redis_client, efi_client): evita recriar o cache em
/// memória a cada rebuild de widget que dependa do ApiClient.
final deviceFingerprint = SharedPreferencesDeviceFingerprint();

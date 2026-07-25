import 'package:cubemine_pix/core/device_fingerprint.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('SharedPreferencesDeviceFingerprint', () {
    test('generates a device id on first call and persists it', () async {
      SharedPreferences.setMockInitialValues({});
      final fingerprint = SharedPreferencesDeviceFingerprint();

      final deviceId = await fingerprint.getDeviceId();

      expect(deviceId, isNotEmpty);
      // Formato de UUID v4: 8-4-4-4-12 hex, versão "4" e variante RFC 4122.
      expect(
        deviceId,
        matches(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')),
      );

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('device_id'), deviceId);
    });

    test('reuses the same id across calls on the same instance', () async {
      SharedPreferences.setMockInitialValues({});
      final fingerprint = SharedPreferencesDeviceFingerprint();

      final first = await fingerprint.getDeviceId();
      final second = await fingerprint.getDeviceId();

      expect(second, first);
    });

    test('reuses the persisted id across a fresh instance (new app session)', () async {
      SharedPreferences.setMockInitialValues({});
      final firstSession = SharedPreferencesDeviceFingerprint();
      final firstId = await firstSession.getDeviceId();

      // Uma nova instância simula uma nova sessão do mesmo app instalado --
      // o valor já persistido em disco (shared_preferences) tem que ser
      // reaproveitado, não gerado de novo.
      final secondSession = SharedPreferencesDeviceFingerprint();
      final secondId = await secondSession.getDeviceId();

      expect(secondId, firstId);
    });

    test('does not regenerate when a value is already persisted (fresh install-like state)', () async {
      SharedPreferences.setMockInitialValues({'device_id': 'pre-existing-device-id'});
      final fingerprint = SharedPreferencesDeviceFingerprint();

      final deviceId = await fingerprint.getDeviceId();

      expect(deviceId, 'pre-existing-device-id');
    });
  });
}

import 'dart:convert';

import 'package:cubemine_pix/core/api_client.dart';
import 'package:cubemine_pix/core/api_exception.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  group('ApiClient', () {
    test('attaches bearer token from idTokenProvider on authenticated requests', () async {
      http.Request? capturedRequest;
      final mockClient = MockClient((request) async {
        capturedRequest = request;
        return http.Response(jsonEncode({'ok': true}), 200);
      });

      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: mockClient,
        idTokenProvider: () async => 'my-token',
      );

      final result = await client.get('/wallet/balance');

      expect(capturedRequest!.headers['Authorization'], 'Bearer my-token');
      expect(result, {'ok': true});
    });

    test('does not attach Authorization header when auth is false', () async {
      http.Request? capturedRequest;
      final mockClient = MockClient((request) async {
        capturedRequest = request;
        return http.Response('{}', 200);
      });

      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: mockClient,
        idTokenProvider: () async => 'my-token',
      );

      await client.post('/ads/callback', body: {'a': 1}, auth: false);

      expect(capturedRequest!.headers.containsKey('Authorization'), isFalse);
    });

    test('attaches X-Device-Id from deviceIdProvider on every request', () async {
      http.Request? capturedGetRequest;
      http.Request? capturedPostRequest;
      final mockClient = MockClient((request) async {
        if (request.method == 'GET') {
          capturedGetRequest = request;
        } else {
          capturedPostRequest = request;
        }
        return http.Response('{}', 200);
      });

      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: mockClient,
        deviceIdProvider: () async => 'device-abc-123',
      );

      await client.get('/wallet/balance');
      await client.post('/auth/register', body: {});

      expect(capturedGetRequest!.headers['X-Device-Id'], 'device-abc-123');
      expect(capturedPostRequest!.headers['X-Device-Id'], 'device-abc-123');
    });

    test('omits X-Device-Id when deviceIdProvider is not configured', () async {
      http.Request? capturedRequest;
      final mockClient = MockClient((request) async {
        capturedRequest = request;
        return http.Response('{}', 200);
      });

      final client = ApiClient(baseUrl: 'https://api.test', httpClient: mockClient);

      await client.post('/auth/register', body: {});

      expect(capturedRequest!.headers.containsKey('X-Device-Id'), isFalse);
    });

    test('sends extra headers such as Idempotency-Key', () async {
      http.Request? capturedRequest;
      final mockClient = MockClient((request) async {
        capturedRequest = request;
        return http.Response('{}', 200);
      });

      final client = ApiClient(baseUrl: 'https://api.test', httpClient: mockClient);

      await client.post(
        '/mining/collect',
        body: {'session_id': 1},
        extraHeaders: {'Idempotency-Key': 'abc-123'},
      );

      expect(capturedRequest!.headers['Idempotency-Key'], 'abc-123');
    });

    test('throws an ApiException instead of hanging forever when the server never responds', () async {
      // Reproduz o bug reportado: sem timeout nenhum, uma chamada sem
      // resposta (cold start do Render indo além do esperado, conexão
      // travada por qualquer outro motivo) ficava esperando indefinidamente
      // -- a tela de carregamento nunca resolvia sozinha.
      final mockClient = MockClient((request) async {
        await Future.delayed(const Duration(seconds: 5));
        return http.Response('{}', 200);
      });

      final client = ApiClient(
        baseUrl: 'https://api.test',
        httpClient: mockClient,
        requestTimeout: const Duration(milliseconds: 50),
      );

      final stopwatch = Stopwatch()..start();
      await expectLater(
        () => client.get('/wallet/balance'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 0)),
      );
      stopwatch.stop();

      // Bem menor que os 5s que o mock levaria pra responder de verdade --
      // prova que o timeout interrompeu a espera, não que só coincidiu de
      // ser rápido.
      expect(stopwatch.elapsed, lessThan(const Duration(seconds: 1)));
    });

    test('throws ApiException with the backend detail message on error responses', () async {
      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'mining session is not ready to collect'}),
          409,
        );
      });

      final client = ApiClient(baseUrl: 'https://api.test', httpClient: mockClient);

      await expectLater(
        () => client.post('/mining/collect', body: {'session_id': 1}),
        throwsA(
          isA<ApiException>()
              .having((e) => e.statusCode, 'statusCode', 409)
              .having((e) => e.message, 'message', 'mining session is not ready to collect'),
        ),
      );
    });
  });
}

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

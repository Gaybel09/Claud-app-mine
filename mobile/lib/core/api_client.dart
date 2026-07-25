import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_exception.dart';

/// Provedor do Firebase ID token atual do usuário autenticado. Devolve null
/// se não houver usuário logado.
typedef IdTokenProvider = Future<String?> Function();

/// Provedor do device_id persistido localmente (ver DeviceFingerprint).
typedef DeviceIdProvider = Future<String?> Function();

/// Wrapper HTTP fino sobre o backend: anexa o Bearer token do Firebase em
/// toda chamada autenticada, o header X-Device-Id (antifraude, seção 11) em
/// toda chamada, e converte respostas de erro em [ApiException].
class ApiClient {
  ApiClient({
    required this.baseUrl,
    http.Client? httpClient,
    this.idTokenProvider,
    this.deviceIdProvider,
  }) : _client = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _client;
  final IdTokenProvider? idTokenProvider;
  final DeviceIdProvider? deviceIdProvider;

  Future<Map<String, String>> _headers({
    required bool auth,
    Map<String, String>? extra,
  }) async {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (auth && idTokenProvider != null) {
      final token = await idTokenProvider!();
      if (token != null) {
        headers['Authorization'] = 'Bearer $token';
      }
    }
    if (deviceIdProvider != null) {
      final deviceId = await deviceIdProvider!();
      if (deviceId != null) {
        headers['X-Device-Id'] = deviceId;
      }
    }
    if (extra != null) headers.addAll(extra);
    return headers;
  }

  Future<dynamic> get(
    String path, {
    Map<String, String>? query,
    bool auth = true,
  }) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: query);
    final response = await _client.get(uri, headers: await _headers(auth: auth));
    return _handle(response);
  }

  Future<dynamic> post(
    String path, {
    Object? body,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final response = await _client.post(
      uri,
      headers: await _headers(auth: auth, extra: extraHeaders),
      body: body == null ? null : jsonEncode(body),
    );
    return _handle(response);
  }

  dynamic _handle(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      return jsonDecode(response.body);
    }

    String message = response.body;
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        message = decoded['detail'].toString();
      }
    } catch (_) {
      // corpo de erro não é JSON -- usa o texto cru mesmo.
    }
    throw ApiException(statusCode: response.statusCode, message: message);
  }
}

import 'dart:async';
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
    this.requestTimeout = const Duration(seconds: 60),
  }) : _client = httpClient ?? http.Client();

  final String baseUrl;
  final http.Client _client;
  final IdTokenProvider? idTokenProvider;
  final DeviceIdProvider? deviceIdProvider;

  /// Sem isso, uma chamada HTTP sem resposta (cold start do Render free
  /// tier -- documentado em até ~50s --, ou uma conexão que trava por
  /// qualquer outro motivo) ficava esperando indefinidamente: a tela de
  /// carregamento nunca resolvia sozinha, só fechando e reabrindo o app.
  /// 60s dá folga sobre o cold start documentado sem deixar uma conexão
  /// travada pendurada por minutos.
  final Duration requestTimeout;

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
    final response = await _withTimeout(
      _client.get(uri, headers: await _headers(auth: auth)),
    );
    return _handle(response);
  }

  Future<dynamic> post(
    String path, {
    Object? body,
    bool auth = true,
    Map<String, String>? extraHeaders,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final response = await _withTimeout(
      _client.post(
        uri,
        headers: await _headers(auth: auth, extra: extraHeaders),
        body: body == null ? null : jsonEncode(body),
      ),
    );
    return _handle(response);
  }

  Future<dynamic> patch(
    String path, {
    Object? body,
    bool auth = true,
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final response = await _withTimeout(
      _client.patch(
        uri,
        headers: await _headers(auth: auth),
        body: body == null ? null : jsonEncode(body),
      ),
    );
    return _handle(response);
  }

  Future<http.Response> _withTimeout(Future<http.Response> request) {
    return request.timeout(
      requestTimeout,
      onTimeout: () => throw const ApiException(
        statusCode: 0,
        message: 'Sem resposta do servidor. Verifique sua conexão e tente novamente.',
      ),
    );
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

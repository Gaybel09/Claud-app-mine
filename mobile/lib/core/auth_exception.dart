/// Erro de autenticação traduzido do Firebase Auth para um tipo próprio,
/// testável sem depender do pacote firebase_auth diretamente nas telas (ver
/// AuthService/FirebaseAuthService) -- mesma ideia de ApiException para
/// erros HTTP do backend.
class AuthException implements Exception {
  const AuthException({required this.code, required this.message});

  /// Código original do Firebase (ex: "email-already-in-use"), para quem
  /// chama decidir uma ação específica sem precisar comparar a mensagem
  /// (que é texto livre, traduzido para exibição).
  final String code;
  final String message;

  @override
  String toString() => 'AuthException($code): $message';
}

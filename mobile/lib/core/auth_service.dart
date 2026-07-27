import 'package:firebase_auth/firebase_auth.dart' as fb;

import 'auth_exception.dart';

/// Identidade mínima do usuário autenticado no Firebase, desacoplada do
/// pacote firebase_auth para o resto do app (e os testes) não precisarem
/// conhecer os tipos do Firebase.
class AppAuthUser {
  const AppAuthUser({required this.uid, required this.email});

  final String uid;
  final String? email;
}

/// Abstração sobre o provedor de autenticação (seção 2: Firebase Auth).
/// Testes de tela usam uma implementação fake em vez do Firebase de verdade.
abstract class AuthService {
  Stream<AppAuthUser?> authStateChanges();

  AppAuthUser? get currentUser;

  Future<AppAuthUser> registerWithEmailPassword(String email, String password);

  Future<AppAuthUser> signInWithEmailPassword(String email, String password);

  /// Token de ID do Firebase para autenticar chamadas ao backend via
  /// `Authorization: Bearer <token>`.
  Future<String?> getIdToken({bool forceRefresh = false});

  Future<void> signOut();
}

class FirebaseAuthService implements AuthService {
  FirebaseAuthService([fb.FirebaseAuth? instance])
      : _auth = instance ?? fb.FirebaseAuth.instance;

  final fb.FirebaseAuth _auth;

  AppAuthUser? _toAppUser(fb.User? user) {
    if (user == null) return null;
    return AppAuthUser(uid: user.uid, email: user.email);
  }

  @override
  Stream<AppAuthUser?> authStateChanges() {
    return _auth.authStateChanges().map(_toAppUser);
  }

  @override
  AppAuthUser? get currentUser => _toAppUser(_auth.currentUser);

  @override
  Future<AppAuthUser> registerWithEmailPassword(String email, String password) async {
    try {
      final credential = await _auth.createUserWithEmailAndPassword(
        email: email,
        password: password,
      );
      return _toAppUser(credential.user)!;
    } on fb.FirebaseAuthException catch (e) {
      // "email-already-in-use" é o caso prático mais comum de uma tentativa
      // anterior ter criado a conta no Firebase mesmo o app tendo mostrado
      // erro (ex: a chamada a POST /auth/register que vem depois travou/
      // caiu por instabilidade de rede, sem o app nunca confirmar) --
      // traduzido aqui pra RegisterScreen poder guiar o usuário pro login
      // em vez de mostrar um erro genérico de "não foi possível criar".
      throw AuthException(code: e.code, message: _translateAuthError(e.code));
    }
  }

  @override
  Future<AppAuthUser> signInWithEmailPassword(String email, String password) async {
    final credential = await _auth.signInWithEmailAndPassword(
      email: email,
      password: password,
    );
    return _toAppUser(credential.user)!;
  }

  @override
  Future<String?> getIdToken({bool forceRefresh = false}) {
    final user = _auth.currentUser;
    if (user == null) return Future.value(null);
    return user.getIdToken(forceRefresh);
  }

  @override
  Future<void> signOut() => _auth.signOut();

  String _translateAuthError(String code) {
    switch (code) {
      case 'email-already-in-use':
        return 'Já existe uma conta com esse e-mail. Tente entrar em vez de criar uma nova.';
      case 'weak-password':
        return 'Senha muito fraca. Use pelo menos 6 caracteres.';
      case 'invalid-email':
        return 'E-mail inválido.';
      default:
        return 'Não foi possível criar a conta. Tente novamente.';
    }
  }
}

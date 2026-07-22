import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'app.dart';
import 'firebase_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  try {
    await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  } catch (error) {
    // Só o Android tem credenciais reais até agora (firebase_options.dart).
    // Web/iOS/desktop lançam UnsupportedError até rodar `flutterfire
    // configure` para essas plataformas -- o app ainda sobe, mas login/
    // cadastro vão falhar em runtime nelas até lá.
    debugPrint('Firebase not configured for this platform yet: $error');
  }

  runApp(const CubeMinePixApp());
}

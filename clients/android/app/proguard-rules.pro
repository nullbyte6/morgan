-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keep,includedescriptorclasses class com.xdg.morgan.**$$serializer { *; }
-keepclassmembers class com.xdg.morgan.** {
    *** Companion;
}
-keepclasseswithmembers class com.xdg.morgan.** {
    kotlinx.serialization.KSerializer serializer(...);
}

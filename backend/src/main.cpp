#include <iostream>
#include <string>

int main(int argc, char* argv[]) {
    std::cout << "🚀 Exail Edge Backend V2 Démarré !" << std::endl;
    std::cout << "Écoute sur le port 9090 (Simulation)..." << std::endl;
    
    if (argc > 1 && std::string(argv[1]) == "--health-check") {
        std::cout << "STATUS: OK" << std::endl;
        return 0;
    }

    while(true) {
    }
    
    return 0;
}

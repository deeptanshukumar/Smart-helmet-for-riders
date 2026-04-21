# Smart Helmet for Riders

**Team Members:**  
Deeptanshu Kumar (PES1UG24AM357)  
Chiranth R (PES1UG24AM354)  

## Overview

**Smart Helmet for Riders** is an innovative IoT-based project designed to enhance rider safety through technology integration. This helmet incorporates hardware sensors and microcontrollers to detect helmet usage, check for alcohol consumption, and ensure the ignition of the vehicle is authorized only under safe conditions. The project demonstrates an applied solution to real-world problems related to road safety, particularly for two-wheeler riders.

## Features

- **Helmet Detection:** Ensures that the rider is wearing the helmet, otherwise prevents vehicle ignition.
- **Alcohol Detection:** An onboard sensor checks for alcohol levels; prevents the engine from starting if alcohol is detected beyond a safe threshold.
- **Accident Notification:** (Optional/Planned) In case of a detected accident event, alerts can be sent.
- **Smart Integration:** Utilizes microcontrollers (such as Arduino/Raspberry Pi) for sensor processing and relay automation.
- **User Friendly:** Designed for easy implementation on standard helmets.

## Motivation

According to safety statistics, a significant number of two-wheeler road accidents are exacerbated due to non-usage of helmets and driving under the influence of alcohol. This project aims to automate compliance with these basic safety rules using a technologically empowered and cost-effective solution.

## Technologies Used

- **Programming Languages:**  
  - C/C++ (for microcontroller firmware)
  - Python (optional for advanced integration and testing)
- **Hardware:**  
  - Microcontroller (Arduino/ESP/Raspberry Pi)
  - Alcohol Sensor (e.g., MQ-3)
  - Pressure/Proximity Sensors
  - GSM/Bluetooth Modules (for notification features)
- **Platform:** Embedded systems and IoT prototyping environments

## Getting Started

### Prerequisites

- Arduino IDE / PlatformIO
- Soldering tools and hardware components as per circuit diagram
- Basic knowledge of embedded programming

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/deeptanshukumar/Smart-helmet-for-riders.git
   ```
2. **Circuit Assembly:**
   - Assemble all the hardware components as per the provided circuit diagram.
3. **Firmware:**
   - Load the firmware code onto the microcontroller via Arduino IDE.
   - Update sensor thresholds in code if required.
4. **Testing:**
   - Test alcohol and helmet detection with sample scenarios.
   - Verify engine relay logic operates as intended.

_Note: For advanced features like accident notification, additional modules or code adaptation may be required._

## Demonstration

**Circuit Diagram:**  
![Circuit Diagram](https://github.com/deeptanshukumar/Smart-helmet-for-riders/blob/main/circuit-diagram.png)

**Project Output:**  
![Output Image](https://github.com/deeptanshukumar/Smart-helmet-for-riders/blob/main/output-image.png)


## License

This project is provided as-is for educational use. Adapt and improve as needed for learning or prototyping.

## Acknowledgments

- Faculty and mentors at PES University  
- Open-source community for hardware and IoT project inspiration

---

Feel free to contribute or raise issues if you have suggestions, improvements, or queries regarding the project.

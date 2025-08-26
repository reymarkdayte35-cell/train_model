from flask import Flask, request, jsonify
import joblib
import numpy as np
import subprocess
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["https://kalamansi-yield-system-eudp0z.flutterflow.app"])

# Load the trained model
model = joblib.load('yield_model.pkl')

@app.route('/')
def home():
    return "✅ Yield Prediction API is running!"

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()

        # Extract input features
        temp = float(data['temperature'])
        hum = float(data['humidity'])
        moist = float(data['soil_moisture'])

        # Predict yield
        input_array = np.array([[temp, hum, moist]])
        predicted_yield = model.predict(input_array)[0]

        return jsonify({
            'predicted_yield': round(predicted_yield, 2),
            'input': {
                'temperature': temp,
                'humidity': hum,
                'soil_moisture': moist
            }
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ✅ New endpoint to train the model
@app.route('/train', methods=['POST'])
def train():
    try:
        result = subprocess.run(['python', 'train_model.py'], capture_output=True, text=True, check=True)
        return jsonify({
            'message': '✅ Model training started successfully.',
            'output': result.stdout
        }), 200
    except subprocess.CalledProcessError as e:
        return jsonify({
            'error': '❌ Training failed.',
            'details': e.stderr
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
